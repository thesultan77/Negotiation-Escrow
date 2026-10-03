# NegotiationEscrow

**Bounded AI-Mediated Price Negotiation on GenLayer**

An escrow contract for buyer/seller price negotiation where, if the two
sides can't agree, an AI mediator steps in but is structurally prevented
from inventing a price. It can only ever choose between two numbers the
parties themselves already committed to on-chain.

---

## What it does

1. A **buyer opens a deal**, staking GEN equal to their ceiling (maximum)
   price for whatever is being exchanged.
2. The **seller can counter** with a lower ask, any number of times, as
   long as each counter stays at or below the buyer's original ceiling —
   this is pure negotiation bookkeeping, no funds move yet.
3. The **buyer can accept the current ask at any time**, settling the deal
   immediately: the seller is paid the agreed ask, and the buyer is
   refunded the difference between their original stake and the final
   price.
4. If negotiation stalls (at least two counter-rounds have happened),
   **either party can request AI mediation**. Critically, the LLM mediator
   is never asked to generate a number — it's given only the deal
   description, the buyer's original ceiling, and the seller's current ask,
   and asked to choose exactly one of those two pre-committed values based
   on whether the discount is justified by the deal's substance.
5. The mediator's output is **explicitly validated** (JSON structure,
   field presence, types, and domain of the `choice` field) before any
   state change or fund transfer — the same safety pattern used in
   SemanticDisputeRouter, applied here from the start rather than added
   after review feedback.
6. `cancel_deal` (only before any counter-offer has been made) and
   `claim_timeout_refund` (72h) provide fund-safety exits.

## Why this is different

Most AI-arbitrated contracts ask the LLM to produce a value directly —
a verdict, a category, sometimes even a number. Asking an LLM to *invent* a
settlement price is a much harder consensus problem: validators would need
to agree on an exact numeric output, which is fragile and easy to get
subtly wrong. NegotiationEscrow sidesteps that entirely by never letting
the AI generate a number at all — negotiation (the human/economic part)
happens entirely through on-chain counter-offers between the real parties,
and the AI's only role is a bounded categorical choice between two numbers
that already exist. This makes the hardest part of the mechanism (price
discovery) a normal negotiation, and the AI's job trivially easy to verify
and reach consensus on.

## Architecture

| Concern | Mechanism |
|---|---|
| Deal state | Parallel `TreeMap[str, ...]` fields per deal ID (buyer, seller, description, stake, current ask, round count, status, deadline, final price) |
| Negotiation | `seller_counter` enforces each new ask is positive and never exceeds the buyer's original ceiling |
| AI mediation | `gl.nondet.exec_prompt` inside a closure, reconciled across validators via `gl.eq_principle.prompt_comparative`; the LLM chooses only between two already-committed values, never generates one |
| Output safety | Mediator output is validated (JSON structure, field presence, type, and domain of `choice`) before any state mutation or fund transfer is allowed to proceed |
| Fund safety | Funds only move on `ACCEPTED` (buyer accepts, seller paid + buyer refunded difference), `MEDIATED` (settled per mediator choice), `CANCELLED` (full refund, only before negotiation starts), or a timeout refund |

## Contract methods

### Write

- **`open_deal(description: str, seller_address: str) -> str`** *(payable)*
  Buyer stakes their ceiling price and opens a deal against a specific
  seller. Returns the new `deal_id` (e.g. `"N0"`).
- **`seller_counter(deal_id: str, new_ask: int)`**
  Seller proposes a new, lower ask (must be positive and not exceed the
  buyer's original stake). Increments the round counter.
- **`accept_current_ask(deal_id: str)`**
  Buyer accepts the current ask immediately: seller is paid the ask amount,
  buyer is refunded the remainder of their stake.
- **`request_mediation(deal_id: str) -> str`**
  Either party can trigger AI mediation once at least two counter-rounds
  have occurred. The LLM chooses `FULL_PRICE` (buyer's original ceiling) or
  `DISCOUNTED_PRICE` (seller's current ask) with reasoning; validators reach
  consensus; output is validated; funds settle accordingly. Returns the
  chosen outcome.
- **`cancel_deal(deal_id: str)`**
  Buyer can cancel and reclaim their full stake, but only before any
  counter-offer has been made.
- **`claim_timeout_refund(deal_id: str)`**
  Anyone can trigger a full refund to the buyer once the 72-hour deadline
  has passed with the deal still open.

### View

- **`get_deal(deal_id: str) -> dict`**
  Full current state of a deal (buyer, seller, description, stake, ask,
  round, status, deadline, final price).
- **`get_deal_count() -> int`**

## Tested end-to-end in GenLayer Studio

- `open_deal` confirmed staking 3 GEN as a ceiling price, returning `"N0"`
  with full validator success.
- `seller_counter` confirmed working across two rounds (3 GEN → 2 GEN →
  1.5 GEN), with `get_deal` correctly showing `round: "2"` and the updated
  ask.
- `request_mediation` confirmed reaching `DISCOUNTED_PRICE` with real
  reasoning grounded in the deal description, and full 5/5 validator
  consensus.
- Post-mediation `get_deal` confirmed `status: "MEDIATED"` and
  `final_price` exactly matching the mediator's chosen value (the seller's
  discounted ask), proving the settlement logic correctly executes
  whichever of the two pre-committed numbers was chosen.
- `cancel_deal` confirmed working correctly on a separate deal with zero
  counter-offers made, refunding the buyer in full.
- All test transactions reached `FINALIZED`/`SUCCESS` with supermajority
  validator agreement.

## Deployment

```
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

No VecDB/embeddings dependency needed for this contract. Constructor takes
no arguments. Deploy directly in GenLayer Studio or via `genlayer-js`
against Studionet / Bradbury testnet.

## Notes on design decisions

- The mediator is deliberately restricted to choosing between two
  pre-committed numbers rather than generating a price itself. Numeric
  generation by an LLM is a much harder target for validator consensus than
  a bounded categorical choice — this contract avoids that risk entirely by
  design, not by post-hoc validation alone.
- Output validation (JSON parse, structure, field types, and domain of the
  categorical `choice` field) is applied *before* any fund transfer or
  state change, following the same pattern that was required as a fix in
  an earlier contract (SemanticDisputeRouter) — applied proactively here
  from the first version rather than added after review feedback.
- `seller_counter` enforces `new_ask <= buyer's original stake` on every
  call, so the seller can never accidentally (or adversarially) counter
  above the buyer's ceiling.

## License

MIT
