"""Adaptador EVM real. Nunca sustituye una transacción por un éxito simulado."""
import json
from pathlib import Path
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_abi import encode
from web3 import Web3


def reference(value):
    return Web3.keccak(text=str(value))


def token_number(ticket_id):
    return int(ticket_id)


class ChainClient:
    def __init__(self, settings):
        self.settings = settings
        self.web3 = Web3(Web3.HTTPProvider(settings.chain_rpc_url, request_kwargs={"timeout": 10}))
        if self.web3.eth.chain_id != settings.chain_id:
            raise RuntimeError("Cadena incompatible")
        artifact = Path(__file__).resolve().parents[3] / "contracts" / "artifacts" / "NexoPass.json"
        self.artifact = json.loads(artifact.read_text(encoding="utf-8"))
        self.signer = Account.from_key(settings.relayer_key.get_secret_value()) if settings.relayer_key else None
        if self.signer:
            self.operator = self.signer.address
        else:
            if settings.chain_id != 31337 or urlparse(settings.chain_rpc_url).hostname not in ("127.0.0.1", "localhost"):
                raise RuntimeError("Se requiere una clave de relayer para redes externas")
            self.operator = self.web3.eth.accounts[0]
        address = settings.contract_address
        file = settings.data_directory / "deployment.json"
        if not address and file.exists():
            deployment = json.loads(file.read_text())
            if deployment.get("chain_id") == settings.chain_id and self.web3.eth.get_code(deployment["address"]):
                address = deployment["address"]
        if not address:
            if settings.chain_id != 31337:
                raise RuntimeError("Falta desplegar/configurar el contrato de pruebas")
            factory = self.web3.eth.contract(abi=self.artifact["abi"], bytecode=self.artifact["bytecode"])
            receipt = self.wait(self.send(factory.constructor(self.operator)))
            if receipt is None:
                raise RuntimeError("Despliegue pendiente")
            address = receipt["contractAddress"]
            settings.data_directory.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps({"chain_id": settings.chain_id, "address": address}), encoding="utf-8")
        self.contract = self.web3.eth.contract(address=Web3.to_checksum_address(address), abi=self.artifact["abi"])

    def send(self, function):
        if self.signer:
            transaction = function.build_transaction({"from": self.operator, "nonce": self.web3.eth.get_transaction_count(self.operator, "pending"), "chainId": self.settings.chain_id})
            signed = self.signer.sign_transaction(transaction)
            return Web3.to_hex(self.web3.eth.send_raw_transaction(signed.raw_transaction))
        return Web3.to_hex(function.transact({"from": self.operator}))

    def wait(self, tx_hash):
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=20, poll_latency=0.2)
        if receipt["status"] != 1:
            raise RuntimeError("Transacción revertida")
        return receipt

    def receipt(self, tx_hash):
        from web3.exceptions import TransactionNotFound
        try:
            return self.web3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return None

    def ensure_event(self, event, unit_id):
        ref = reference(event["id"])
        values = tuple(int(event[key].timestamp()) for key in ("starts_at", "ends_at", "doors_open_at", "transfer_deadline"))
        existing = self.contract.functions.events(ref).call()
        if tuple(existing[:4]) != values:
            self.wait(self.send(self.contract.functions.configureEvent(ref, *values)))
        unit_ref = reference(unit_id)
        key = Web3.keccak(encode(["bytes32", "bytes32"], [ref, unit_ref]))
        if not self.contract.functions.allowedUnits(key).call():
            self.wait(self.send(self.contract.functions.allowUnits(ref, [unit_ref])))
        return ref, unit_ref

    def recovered_transaction(self, event_signature, token_id):
        logs = self.web3.eth.get_logs({"address": self.contract.address, "fromBlock": 0, "toBlock": "latest",
            "topics": [Web3.keccak(text=event_signature), "0x" + int(token_id).to_bytes(32, "big").hex()]})
        return Web3.to_hex(logs[-1]["transactionHash"]) if logs else None

    def mint(self, ticket_id, event, unit_id, owner):
        token_id = token_number(ticket_id)
        existing = self.contract.functions.tickets(token_id).call()
        if existing[0] != bytes(32):
            return self.recovered_transaction("TicketIssued(uint256,bytes32,address)", token_id)
        event_ref, unit_ref = self.ensure_event(event, unit_id)
        return self.send(self.contract.functions.mintTicket(token_id, event_ref, unit_ref, Web3.to_checksum_address(owner)))

    def transfer(self, ticket, recipient, owner_key, operation):
        token_id = token_number(ticket["id"])
        op = reference(operation)
        if self.contract.functions.executed(op).call():
            return self.recovered_transaction("TicketReassigned(uint256,uint32)", token_id)
        owner = Account.from_key(owner_key)
        expires = self.web3.eth.get_block("latest")["timestamp"] + 300
        version = ticket["nomination_version"]
        message = Web3.keccak(encode(["uint256", "address", "uint256", "address", "address", "uint32", "uint64", "bytes32"],
            [self.settings.chain_id, self.contract.address, token_id, owner.address,
             Web3.to_checksum_address(recipient), version, expires, op]))
        signature = owner.sign_message(encode_defunct(message)).signature
        return self.send(self.contract.functions.transferAuthorized(token_id, Web3.to_checksum_address(recipient), version, expires, op, signature))

    def consume(self, ticket, owner, operation):
        token_id = token_number(ticket["id"])
        op = reference(operation)
        if self.contract.functions.executed(op).call():
            return self.recovered_transaction("TicketConsumed(uint256,bytes32)", token_id)
        return self.send(self.contract.functions.consume(token_id, Web3.to_checksum_address(owner), ticket["nomination_version"], op))
