from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from web3 import Web3

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

import os
import logging
import uuid


# ==============================
# ENV CONFIGURATION
# ==============================

load_dotenv()


MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://127.0.0.1:27017"
)

DB_NAME = os.getenv(
    "DB_NAME",
    "tpe_crypto"
)


BNB_RPC = os.getenv(
    "BNB_RPC",
    "https://bsc-dataseed.binance.org/"
)


CHAIN_ID = int(
    os.getenv(
        "CHAIN_ID",
        "56"
    )
)


# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


logger = logging.getLogger(
    "TPE_CRYPTO"
)


# ==============================
# DATABASE CONNECTION
# ==============================

mongo_client = AsyncIOMotorClient(
    MONGO_URL
)


db = mongo_client[DB_NAME]


# ==============================
# BLOCKCHAIN CONNECTION
# ==============================

w3 = Web3(
    Web3.HTTPProvider(
        BNB_RPC
    )
)


# ==============================
# MEMORY CACHE
# ==============================

TOKENS = {}

CARD_WALLETS = {}

MERCHANT = None


# ==============================
# MONGO SERIALIZER
# ==============================

def serialize_document(document):

    if document is None:
        return None


    if "_id" in document:

        document["_id"] = str(
            document["_id"]
        )


    return document



# ==============================
# LOAD TOKENS
# ==============================

async def load_tokens():

    tokens = {}


    cursor = db.tokens.find(
        {
            "enabled": True
        }
    )


    async for token in cursor:

        tokens[token["symbol"]] = {

            "name": token.get(
                "name",
                token["symbol"]
            ),

            "contract": Web3.to_checksum_address(
                token["contract"]
            ),

            "chain": token.get(
                "chain",
                "BSC"
            )

        }


    logger.info(
        f"{len(tokens)} token(s) chargé(s)"
    )


    return tokens



# ==============================
# LOAD CARD WALLETS
# ==============================

async def load_card_wallets():

    wallets = {}


    cursor = db.card_wallets.find(
        {
            "status": "active"
        }
    )


    async for wallet in cursor:

        wallets[
            wallet["wallet_address"]
        ] = wallet



    logger.info(
        f"{len(wallets)} wallet(s) carte chargé(s)"
    )


    return wallets



# ==============================
# LOAD MERCHANT
# ==============================

async def load_merchant():

    merchant = await db.merchant_config.find_one(
        {
            "status": "active"
        }
    )


    if merchant:

        logger.info(
            "Configuration marchand chargée"
        )

    else:

        logger.warning(
            "Aucun marchand configuré"
        )


    return merchant



# ==============================
# APPLICATION LIFESPAN
# ==============================

@asynccontextmanager
async def lifespan(app: FastAPI):

    global TOKENS
    global CARD_WALLETS
    global MERCHANT


    try:

        TOKENS = await load_tokens()

        CARD_WALLETS = await load_card_wallets()

        MERCHANT = await load_merchant()


        logger.info(
            "Backend TPE Crypto opérationnel"
        )


    except Exception as e:

        logger.error(
            f"Erreur démarrage : {e}"
        )


    yield


    mongo_client.close()


    logger.info(
        "Backend arrêté"
    )



# ==============================
# FASTAPI APPLICATION
# ==============================

app = FastAPI(

    title="TPE Crypto Backend",

    description="""
Backend de paiement crypto pour terminal TPE.

Fonctionnement :
- Carte JCOP signe la transaction
- Backend prépare la transaction
- Réseau BNB valide le transfert
- MongoDB conserve l'historique
""",

    version="1.0.0",

    lifespan=lifespan

)
# ==============================
# ENUM TRANSACTION STATUS
# ==============================

class TransactionStatus(str, Enum):

    CREATED = "created"

    SIGNED = "signed"

    SENT = "sent"

    CONFIRMED = "confirmed"

    FAILED = "failed"



# ==============================
# PYDANTIC MODELS
# ==============================

class TransactionCreate(BaseModel):

    card_wallet: str

    token_symbol: str

    amount: float

    merchant_wallet: Optional[str] = None



class TransactionResponse(BaseModel):

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )

    card_wallet: str

    merchant_wallet: str

    token_symbol: str

    amount: float

    status: TransactionStatus = TransactionStatus.CREATED

    tx_hash: Optional[str] = None

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



class MerchantConfig(BaseModel):

    wallet_address: str



class SignedTransaction(BaseModel):

    transaction_id: str

    signed_transaction: str



class BroadcastTransaction(BaseModel):

    transaction_id: str

    raw_transaction: str



# ==============================
# BASIC ROUTES
# ==============================

@app.get("/")
async def root():

    return {

        "message": "TPE Crypto Backend",

        "status": "online",

        "chain_id": CHAIN_ID

    }



@app.get("/health")
async def health():

    return {

        "status": "ok"

    }



# ==============================
# TOKEN API
# ==============================

@app.get("/tokens")
async def get_tokens():

    return TOKENS



# ==============================
# CARD WALLET API
# ==============================

@app.get("/card-wallets")
async def get_card_wallets():

    return CARD_WALLETS



# ==============================
# MERCHANT API
# ==============================

@app.get("/merchant")
async def get_merchant():


    if MERCHANT is None:

        return {

            "configured": False

        }


    return serialize_document(
        MERCHANT.copy()
    )



# ==============================
# ERC20 ABI
# ==============================

ERC20_ABI = [

    {

        "constant": True,

        "inputs": [],

        "name": "decimals",

        "outputs": [

            {

                "name": "",

                "type": "uint8"

            }

        ],

        "type": "function"

    },

    {

        "constant": True,

        "inputs": [],

        "name": "symbol",

        "outputs": [

            {

                "name": "",

                "type": "string"

            }

        ],

        "type": "function"

    }

]



# ==============================
# GET TOKEN DETAILS
# ==============================

async def get_token_details(symbol: str):


    token = TOKENS.get(
        symbol.upper()
    )


    if token is None:

        return None



    contract = w3.eth.contract(

        address=token["contract"],

        abi=ERC20_ABI

    )


    try:

        decimals = contract.functions.decimals().call()


    except Exception:

        decimals = 18



    return {

        "symbol": symbol.upper(),

        "contract": token["contract"],

        "decimals": decimals

    }



# ==============================
# CREATE TRANSACTION
# ==============================

@app.post("/transactions/create")
async def create_transaction(
    data: TransactionCreate
):


    token = await get_token_details(
        data.token_symbol
    )


    if token is None:

        raise HTTPException(

            status_code=400,

            detail="Token inconnu"

        )



    if data.card_wallet not in CARD_WALLETS:

        raise HTTPException(

            status_code=400,

            detail="Wallet carte inconnu"

        )



    if MERCHANT is None:

        raise HTTPException(

            status_code=400,

            detail="Aucun marchand configuré"

        )



    merchant_wallet = MERCHANT[
        "wallet_address"
    ]



    amount_base = int(

        data.amount *

        (

            10 ** token["decimals"]

        )

    )



    transaction = {


        "card_wallet": data.card_wallet,


        "merchant_wallet": merchant_wallet,


        "token_symbol": token["symbol"],


        "token_contract": token["contract"],


        "amount": data.amount,


        "amount_base": str(amount_base),


        "decimals": token["decimals"],


        "status": TransactionStatus.CREATED.value,


        "created_at": datetime.utcnow()


    }



    result = await db.transactions.insert_one(

        transaction

    )



    return {


        "success": True,


        "transaction_id": str(

            result.inserted_id

        ),


        "status": transaction["status"],


        "amount": transaction["amount"],


        "token_symbol": transaction["token_symbol"]

    }
# ==============================
# ERC20 TRANSFER ABI
# ==============================

ERC20_TRANSFER_ABI = [

    {

        "constant": False,

        "inputs": [

            {

                "name": "_to",

                "type": "address"

            },

            {

                "name": "_value",

                "type": "uint256"

            }

        ],

        "name": "transfer",

        "outputs": [

            {

                "name": "",

                "type": "bool"

            }

        ],

        "type": "function"

    }

]



# ==============================
# PREPARE TRANSACTION
# ==============================

@app.post("/transactions/prepare")
async def prepare_transaction(
    transaction_id: str
):


    try:

        transaction = await db.transactions.find_one(

            {

                "_id": ObjectId(transaction_id)

            }

        )


    except Exception:

        raise HTTPException(

            status_code=400,

            detail="Identifiant transaction invalide"

        )



    if transaction is None:

        raise HTTPException(

            status_code=404,

            detail="Transaction introuvable"

        )



    token_contract = w3.eth.contract(

        address=transaction["token_contract"],

        abi=ERC20_TRANSFER_ABI

    )



    sender = Web3.to_checksum_address(

        transaction["card_wallet"]

    )


    receiver = Web3.to_checksum_address(

        transaction["merchant_wallet"]

    )



    try:


        nonce = w3.eth.get_transaction_count(

            sender

        )


        gas_price = w3.eth.gas_price



        tx = token_contract.functions.transfer(

            receiver,

            int(transaction["amount_base"])

        ).build_transaction(

            {

                "chainId": CHAIN_ID,

                "from": sender,

                "nonce": nonce,

                "gasPrice": gas_price

            }

        )


    except Exception as e:


        raise HTTPException(

            status_code=500,

            detail=str(e)

        )



    await db.transactions.update_one(

        {

            "_id": ObjectId(transaction_id)

        },

        {

            "$set": {

                "unsigned_transaction": tx,

                "status": TransactionStatus.CREATED.value

            }

        }

    )



    return {


        "success": True,


        "transaction_id": transaction_id,


        "unsigned_transaction": tx

    }





# ==============================
# RECEIVE CARD SIGNATURE
# ==============================

@app.post("/transactions/sign")
async def receive_signature(

    data: SignedTransaction

):


    try:

        transaction = await db.transactions.find_one(

            {

                "_id": ObjectId(data.transaction_id)

            }

        )


    except Exception:

        raise HTTPException(

            status_code=400,

            detail="ID transaction invalide"

        )



    if transaction is None:

        raise HTTPException(

            status_code=404,

            detail="Transaction introuvable"

        )



    await db.transactions.update_one(

        {

            "_id": ObjectId(data.transaction_id)

        },

        {

            "$set": {

                "signed_transaction": data.signed_transaction,

                "status": TransactionStatus.SIGNED.value

            }

        }

    )



    return {


        "success": True,


        "message": "Signature carte reçue",


        "transaction_id": data.transaction_id

    }





# ==============================
# BROADCAST SIGNED TRANSACTION
# ==============================

@app.post("/transactions/broadcast")
async def broadcast_transaction(

    data: BroadcastTransaction

):


    try:

        transaction = await db.transactions.find_one(

            {

                "_id": ObjectId(data.transaction_id)

            }

        )


    except Exception:

        raise HTTPException(

            status_code=400,

            detail="ID transaction invalide"

        )



    if transaction is None:

        raise HTTPException(

            status_code=404,

            detail="Transaction introuvable"

        )



    try:


        raw_tx = bytes.fromhex(

            data.raw_transaction.replace(

                "0x",

                ""

            )

        )



        tx_hash = w3.eth.send_raw_transaction(

            raw_tx

        )



        tx_hash_hex = tx_hash.hex()



        await db.transactions.update_one(

            {

                "_id": ObjectId(data.transaction_id)

            },

            {

                "$set": {

                    "tx_hash": tx_hash_hex,

                    "status": TransactionStatus.SENT.value

                }

            }

        )



        return {


            "success": True,


            "tx_hash": tx_hash_hex

        }



    except Exception as e:


        await db.transactions.update_one(

            {

                "_id": ObjectId(data.transaction_id)

            },

            {

                "$set": {

                    "error": str(e),

                    "status": TransactionStatus.FAILED.value

                }

            }

        )



        raise HTTPException(

            status_code=500,

            detail=str(e)

        )
# ==============================
# UPDATE MERCHANT WALLET
# ==============================

@app.post("/merchant/update")
async def update_merchant(

    data: MerchantConfig

):


    global MERCHANT


    try:

        wallet = Web3.to_checksum_address(

            data.wallet_address

        )


    except Exception:

        raise HTTPException(

            status_code=400,

            detail="Adresse wallet invalide"

        )



    merchant_data = {


        "wallet_address": wallet,


        "status": "active",


        "updated_at": datetime.utcnow()


    }



    await db.merchant_config.update_many(

        {},

        {

            "$set": {

                "status": "inactive"

            }

        }

    )



    result = await db.merchant_config.insert_one(

        merchant_data

    )



    MERCHANT = merchant_data



    return {


        "success": True,


        "merchant_id": str(

            result.inserted_id

        ),


        "wallet_address": wallet

    }





# ==============================
# VALIDATION HELPERS
# ==============================

def validate_wallet(address: str):


    try:

        return Web3.is_address(

            address

        )


    except Exception:

        return False





def validate_amount(amount: float):


    return amount > 0





# ==============================
# VALIDATE WALLET API
# ==============================

@app.get("/validate/wallet/{address}")
async def validate_wallet_api(

    address: str

):


    return {


        "address": address,


        "valid": validate_wallet(

            address

        )

    }





# ==============================
# SYSTEM STATUS
# ==============================

@app.get("/system/status")
async def system_status():


    mongo_status = False

    bnb_status = False



    try:

        await db.command(

            "ping"

        )

        mongo_status = True


    except Exception:


        mongo_status = False





    try:

        bnb_status = w3.is_connected()


    except Exception:


        bnb_status = False




    return {


        "backend": True,


        "mongodb": mongo_status,


        "bnb_chain": bnb_status,


        "chain_id": CHAIN_ID,


        "tokens_loaded": len(TOKENS),


        "cards_loaded": len(CARD_WALLETS),


        "merchant_configured": MERCHANT is not None

    }





# ==============================
# START MESSAGE
# ==============================

logger.info(

    "Server.py chargé correctement"

)
