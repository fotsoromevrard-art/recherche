from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from web3 import Web3

import os
import logging


# ==============================
# ENV CONFIG
# ==============================

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
DB_NAME = os.getenv("DB_NAME", "tpe_crypto")

BNB_RPC = os.getenv(
    "BNB_RPC",
    "https://bsc-dataseed.binance.org/"
)

CHAIN_ID = int(
    os.getenv("CHAIN_ID", "56")
)


# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger("TPE_CRYPTO")


# ==============================
# MONGODB
# ==============================

mongo_client = AsyncIOMotorClient(MONGO_URL)

db = mongo_client[DB_NAME]


# ==============================
# BNB SMART CHAIN
# ==============================

w3 = Web3(
    Web3.HTTPProvider(BNB_RPC)
)


# ==============================
# MEMORY CONFIGURATION
# ==============================

TOKENS = {}

CARD_WALLETS = {}

MERCHANT = None


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
            "name": token["name"],
            "contract": Web3.to_checksum_address(
                token["contract"]
            ),
            "chain": token["chain"]
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

        wallets[wallet["wallet_address"]] = wallet

    logger.info(
        f"{len(wallets)} wallet(s) carte chargé(s)"
    )

    return wallets


# ==============================
# LOAD MERCHANT CONFIG
# ==============================

async def load_merchant():

    merchant = await db.merchant_config.find_one(
        {
            "status": "active"
        }
    )

    if merchant:

        logger.info(
            "Wallet marchand chargé"
        )

    else:

        logger.warning(
            "Aucun wallet marchand configuré"
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


    TOKENS = await load_tokens()

    CARD_WALLETS = await load_card_wallets()

    MERCHANT = await load_merchant()


    logger.info(
        "Backend TPE Crypto démarré"
    )


    yield


    mongo_client.close()

    logger.info(
        "Backend arrêté"
    )


# ==============================
# FASTAPI
# ==============================

app = FastAPI(
    title="TPE Crypto Backend",
    version="1.0.0",
    lifespan=lifespan
)
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
# CONFIGURATION API
# ==============================

@app.get("/tokens")
async def get_tokens():

    return TOKENS


@app.get("/card-wallets")
async def get_card_wallets():

    return CARD_WALLETS


@app.get("/merchant")
async def get_merchant():

    if MERCHANT is None:

        return {
            "configured": False
        }

    return MERCHANT
# ==============================
# PYDANTIC MODELS
# ==============================

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class TransactionStatus(str, Enum):

    CREATED = "created"
    SIGNED = "signed"
    SENT = "sent"
    CONFIRMED = "confirmed"
    FAILED = "failed"


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
# ==============================
# ERC20 STANDARD ABI
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
# TOKEN INFORMATION
# ==============================

async def get_token_details(symbol: str):

    token = TOKENS.get(symbol.upper())

    if token is None:

        return None


    contract = w3.eth.contract(
        address=token["contract"],
        abi=ERC20_ABI
    )


    decimals = contract.functions.decimals().call()


    return {
        "symbol": symbol.upper(),
        "contract": token["contract"],
        "decimals": decimals
    }


# ==============================
# CREATE TRANSACTION
# ==============================

@app.post("/transactions/create")
async def create_transaction(data: TransactionCreate):


    token = await get_token_details(
        data.token_symbol
    )


    if token is None:

        return {
            "success": False,
            "error": "Token inconnu"
        }


    if data.card_wallet not in CARD_WALLETS:

        return {
            "success": False,
            "error": "Wallet carte inconnu"
        }


    if MERCHANT is None:

        return {
            "success": False,
            "error": "Aucun marchand configuré"
        }


    merchant_wallet = MERCHANT["wallet_address"]


    amount_base = int(
        data.amount * (10 ** token["decimals"])
    )


    transaction = {

        "card_wallet": data.card_wallet,

        "merchant_wallet": merchant_wallet,

        "token_symbol": token["symbol"],

        "token_contract": token["contract"],

        "amount": data.amount,

        "amount_base": str(amount_base),

        "decimals": token["decimals"],

        "status": TransactionStatus.CREATED,

        "created_at": datetime.utcnow()

    }


    result = await db.transactions.insert_one(
        transaction
    )


    return {

        "success": True,

        "transaction_id": str(result.inserted_id),

        "transaction": transaction

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
# PREPARE BLOCKCHAIN TRANSACTION
# ==============================

@app.post("/transactions/prepare")
async def prepare_transaction(transaction_id: str):


    transaction = await db.transactions.find_one(
        {
            "_id": ObjectId(transaction_id)
        }
    )


    if transaction is None:

        return {
            "success": False,
            "error": "Transaction introuvable"
        }


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


    await db.transactions.update_one(
        {
            "_id": ObjectId(transaction_id)
        },
        {
            "$set": {
                "unsigned_transaction": tx,
                "status": TransactionStatus.CREATED
            }
        }
    )


    return {

        "success": True,

        "transaction_id": transaction_id,

        "unsigned_transaction": tx

    }
# ==============================
# MONGODB OBJECT ID
# ==============================

from bson import ObjectId


# ==============================
# GET TRANSACTION
# ==============================

@app.get("/transactions/{transaction_id}")
async def get_transaction(transaction_id: str):

    transaction = await db.transactions.find_one(
        {
            "_id": ObjectId(transaction_id)
        }
    )

    if transaction is None:

        return {
            "success": False,
            "error": "Transaction introuvable"
        }


    transaction["_id"] = str(
        transaction["_id"]
    )


    return {
        "success": True,
        "transaction": transaction
    }


# ==============================
# TRANSACTION HISTORY
# ==============================

@app.get("/transactions")
async def get_transactions():

    transactions = []

    cursor = db.transactions.find().sort(
        "created_at",
        -1
    )


    async for transaction in cursor:

        transaction["_id"] = str(
            transaction["_id"]
        )

        transactions.append(
            transaction
        )


    return {
        "success": True,
        "count": len(transactions),
        "transactions": transactions
    }
# ==============================
# SIGNED TRANSACTION MODEL
# ==============================

class SignedTransaction(BaseModel):

    transaction_id: str

    signed_transaction: str


# ==============================
# RECEIVE CARD SIGNATURE
# ==============================

@app.post("/transactions/sign")
async def receive_signature(
    data: SignedTransaction
):


    transaction = await db.transactions.find_one(
        {
            "_id": ObjectId(data.transaction_id)
        }
    )


    if transaction is None:

        return {
            "success": False,
            "error": "Transaction introuvable"
        }


    await db.transactions.update_one(
        {
            "_id": ObjectId(data.transaction_id)
        },
        {
            "$set": {
                "signed_transaction": data.signed_transaction,
                "status": TransactionStatus.SIGNED
            }
        }
    )


    return {

        "success": True,

        "message": "Signature reçue",

        "transaction_id": data.transaction_id

    }
# ==============================
# SEND SIGNED TRANSACTION TO BNB
# ==============================

class BroadcastTransaction(BaseModel):

    transaction_id: str

    raw_transaction: str


@app.post("/transactions/broadcast")
async def broadcast_transaction(
    data: BroadcastTransaction
):


    transaction = await db.transactions.find_one(
        {
            "_id": ObjectId(data.transaction_id)
        }
    )


    if transaction is None:

        return {
            "success": False,
            "error": "Transaction introuvable"
        }


    try:

        tx_hash = w3.eth.send_raw_transaction(
            bytes.fromhex(
                data.raw_transaction.replace(
                    "0x",
                    ""
                )
            )
        )


        tx_hash_hex = tx_hash.hex()


        await db.transactions.update_one(
            {
                "_id": ObjectId(data.transaction_id)
            },
            {
                "$set": {
                    "tx_hash": tx_hash_hex,
                    "status": TransactionStatus.SENT
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
                    "status": TransactionStatus.FAILED
                }
            }
        )


        return {

            "success": False,

            "error": str(e)

        }
# ==============================
# CHECK BLOCKCHAIN CONFIRMATION
# ==============================

@app.get("/transactions/{transaction_id}/status")
async def check_transaction_status(
    transaction_id: str
):


    transaction = await db.transactions.find_one(
        {
            "_id": ObjectId(transaction_id)
        }
    )


    if transaction is None:

        return {
            "success": False,
            "error": "Transaction introuvable"
        }


    if "tx_hash" not in transaction:

        return {

            "success": True,

            "status": transaction["status"]

        }


    try:

        receipt = w3.eth.get_transaction_receipt(
            transaction["tx_hash"]
        )


        if receipt is None:

            return {

                "success": True,

                "status": "pending"

            }


        if receipt["status"] == 1:


            await db.transactions.update_one(

                {
                    "_id": ObjectId(transaction_id)
                },

                {
                    "$set": {
                        "status": TransactionStatus.CONFIRMED,
                        "block_number": receipt["blockNumber"]
                    }
                }

            )


            return {

                "success": True,

                "status": "confirmed",

                "block": receipt["blockNumber"]

            }


        else:


            await db.transactions.update_one(

                {
                    "_id": ObjectId(transaction_id)
                },

                {
                    "$set": {
                        "status": TransactionStatus.FAILED
                    }
                }

            )


            return {

                "success": True,

                "status": "failed"

            }


    except Exception as e:


        return {

            "success": False,

            "error": str(e)

        }
# ==============================
# MERCHANT CONFIGURATION MODEL
# ==============================

class MerchantConfig(BaseModel):

    wallet_address: str


# ==============================
# UPDATE MERCHANT WALLET
# ==============================

@app.post("/merchant/update")
async def update_merchant(
    data: MerchantConfig
):


    wallet = Web3.to_checksum_address(
        data.wallet_address
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


    global MERCHANT

    MERCHANT = merchant_data


    return {

        "success": True,

        "merchant_id": str(result.inserted_id),

        "wallet_address": wallet

    }
# ==============================
# VALIDATION HELPERS
# ==============================

def validate_wallet(address: str):

    try:

        return Web3.is_address(address)

    except Exception:

        return False



def validate_amount(amount: float):

    return amount > 0



# ==============================
# VALIDATE MERCHANT WALLET
# ==============================

@app.get("/validate/wallet/{address}")
async def validate_wallet_api(address: str):


    valid = validate_wallet(address)


    return {

        "address": address,

        "valid": valid

    }



# ==============================
# BACKEND STATUS
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

        "chain_id": CHAIN_ID

    }
