# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import datetime
import json
from genlayer import *


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass
    class Write:
        pass


class NegotiationEscrow(gl.Contract):
    buyer_map: TreeMap[str, Address]
    seller_map: TreeMap[str, Address]
    description_map: TreeMap[str, str]
    buyer_stake_map: TreeMap[str, u256]
    seller_ask_map: TreeMap[str, u256]
    round_map: TreeMap[str, u256]
    status_map: TreeMap[str, str]
    deadline_map: TreeMap[str, str]
    final_price_map: TreeMap[str, u256]
    deal_counter: u256

    def __init__(self):
        self.deal_counter = u256(0)

    @gl.public.write.payable
    def open_deal(self, description: str, seller_address: str) -> str:
        assert gl.message.value > u256(0), "You must stake a ceiling price."
        deal_id = f"N{self.deal_counter}"
        self.deal_counter += u256(1)

        self.buyer_map[deal_id] = gl.message.sender_address
        self.seller_map[deal_id] = Address(seller_address)
        self.description_map[deal_id] = description
        self.buyer_stake_map[deal_id] = gl.message.value
        self.seller_ask_map[deal_id] = gl.message.value
        self.round_map[deal_id] = u256(0)
        self.status_map[deal_id] = "OPEN"
        self.deadline_map[deal_id] = str(datetime.datetime.now() + datetime.timedelta(hours=72))
        self.final_price_map[deal_id] = u256(0)

        return deal_id

    @gl.public.write
    def seller_counter(self, deal_id: str, new_ask: int) -> None:
        assert self.status_map[deal_id] == "OPEN", "Deal not open"
        assert gl.message.sender_address == self.seller_map[deal_id], "Only the seller can counter"
        ask = u256(new_ask)
        assert ask > u256(0), "Ask must be positive"
        assert ask <= self.buyer_stake_map[deal_id], "Ask cannot exceed the buyer's staked ceiling"
        self.seller_ask_map[deal_id] = ask
        self.round_map[deal_id] = self.round_map[deal_id] + u256(1)

    @gl.public.write
    def accept_current_ask(self, deal_id: str) -> None:
        assert self.status_map[deal_id] == "OPEN", "Deal not open"
        assert gl.message.sender_address == self.buyer_map[deal_id], "Only the buyer can accept"
        ask = self.seller_ask_map[deal_id]
        stake = self.buyer_stake_map[deal_id]
        refund = stake - ask
        _Recipient(self.seller_map[deal_id]).emit_transfer(value=ask)
        if refund > u256(0):
            _Recipient(self.buyer_map[deal_id]).emit_transfer(value=refund)
        self.final_price_map[deal_id] = ask
        self.status_map[deal_id] = "ACCEPTED"

    @gl.public.write
    def request_mediation(self, deal_id: str) -> str:
        assert self.status_map[deal_id] == "OPEN", "Deal not open"
        sender = gl.message.sender_address
        assert sender == self.buyer_map[deal_id] or sender == self.seller_map[deal_id], "Only a party to the deal can request mediation"
        assert self.round_map[deal_id] >= u256(2), "At least 2 counter rounds required before mediation"

        description = self.description_map[deal_id]
        full_price = self.buyer_stake_map[deal_id]
        discounted_price = self.seller_ask_map[deal_id]

        def judge() -> str:
            prompt = f"""You are mediating a price negotiation.

Deal description:
\"\"\"{description}\"\"\"

The buyer's original full price offer is {str(full_price)} wei.
The seller's current discounted ask is {str(discounted_price)} wei.

Based on the deal description, is the seller's discount justified (fair given what's being exchanged), or should the buyer's original full price stand?

Respond with strict JSON only, no markdown, no extra text:
{{"choice": "FULL_PRICE", "reasoning": "<one sentence>"}}
or
{{"choice": "DISCOUNTED_PRICE", "reasoning": "<one sentence>"}}
"""
            return gl.nondet.exec_prompt(prompt)

        raw = gl.eq_principle.prompt_comparative(
            judge,
            "The choice field must match exactly (FULL_PRICE or DISCOUNTED_PRICE). Reasoning wording may vary but must express the same underlying judgment.",
        )

        try:
            parsed = json.loads(raw)
        except Exception:
            raise Exception("Mediator output was not valid JSON; refusing to settle.")

        assert isinstance(parsed, dict), "Mediator output was not a JSON object; refusing to settle."
        assert "choice" in parsed, "Mediator output missing 'choice' field; refusing to settle."
        choice = parsed["choice"]
        assert isinstance(choice, str), "Mediator 'choice' field was not a string; refusing to settle."
        assert choice in ("FULL_PRICE", "DISCOUNTED_PRICE"), "Mediator 'choice' was outside the allowed domain; refusing to settle."

        settle_amount = full_price if choice == "FULL_PRICE" else discounted_price
        refund = full_price - settle_amount

        _Recipient(self.seller_map[deal_id]).emit_transfer(value=settle_amount)
        if refund > u256(0):
            _Recipient(self.buyer_map[deal_id]).emit_transfer(value=refund)

        self.final_price_map[deal_id] = settle_amount
        self.status_map[deal_id] = "MEDIATED"
        return choice

    @gl.public.write
    def cancel_deal(self, deal_id: str) -> None:
        assert self.status_map[deal_id] == "OPEN", "Deal not open"
        assert gl.message.sender_address == self.buyer_map[deal_id], "Only the buyer can cancel"
        assert self.round_map[deal_id] == u256(0), "Cannot cancel after negotiation has started"
        _Recipient(self.buyer_map[deal_id]).emit_transfer(value=self.buyer_stake_map[deal_id])
        self.status_map[deal_id] = "CANCELLED"

    @gl.public.write
    def claim_timeout_refund(self, deal_id: str) -> None:
        assert self.status_map[deal_id] == "OPEN", "Deal not open"
        assert str(datetime.datetime.now()) >= self.deadline_map[deal_id], "Deadline has not passed yet"
        _Recipient(self.buyer_map[deal_id]).emit_transfer(value=self.buyer_stake_map[deal_id])
        self.status_map[deal_id] = "CANCELLED"

    @gl.public.view
    def get_deal(self, deal_id: str) -> dict:
        return {
            "deal_id": deal_id,
            "buyer": str(self.buyer_map[deal_id]),
            "seller": str(self.seller_map[deal_id]),
            "description": self.description_map[deal_id],
            "buyer_stake": str(self.buyer_stake_map[deal_id]),
            "seller_ask": str(self.seller_ask_map[deal_id]),
            "round": str(self.round_map[deal_id]),
            "status": self.status_map[deal_id],
            "deadline": self.deadline_map[deal_id],
            "final_price": str(self.final_price_map[deal_id]),
        }

    @gl.public.view
    def get_deal_count(self) -> int:
        return int(self.deal_counter)
