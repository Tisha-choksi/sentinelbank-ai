"""Generates the synthetic investigation-evaluation dataset.

Every scenario's alert fields are produced by actually running the real
detection engine (`detection.service.run_detection`) against a throwaway
in-memory database -- never hand-typed -- so a scenario's ground truth
can't silently drift from what the system really does. Re-running this
script with the same seed reproduces a byte-identical dataset, so it can
be diffed in version control like any other generated artifact.

Categories 1-6 grade real (or simulated) model *quality*: does it state
the right facts, cite only real evidence, and hedge appropriately.
Categories 7-8 (invalid_citation, model_failure) grade system *resilience*
and are fully deterministic -- they carry a canned `simulated_llm_response`
or `simulated_llm_failure` for a Phase 2 harness to inject instead of a
real model call.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from db import Base
from detection import service
from detection.rules import (
    CIRCULAR_MAX_HOPS,
    CIRCULAR_MIN_HOPS,
    HIGH_VALUE_THRESHOLD,
    VELOCITY_MAX_TRANSFERS,
    VELOCITY_WINDOW_SECONDS,
)
from evaluation.schema import AccountFixture, ScenarioSpec, TransactionFixture

SEED = 20261022
SCENARIOS_PER_CATEGORY = 40
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
DATASET_PATH = Path(__file__).resolve().parent / "dataset" / "scenarios.jsonl"

FORBIDDEN_FRAUD_CLAIMS = [
    "confirmed fraud",
    "is fraudulent",
    "definitely fraud",
    "proven fraud",
]

FAILURE_MODES = ["timeout", "malformed_json", "wrong_shape"]


# --- plumbing: build a throwaway DB, run real detection, capture the result ---


def _fresh_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)(), engine


def _insert_and_detect(
    db, transactions: list[TransactionFixture], accounts: list[AccountFixture]
) -> dict[str, models.Transaction]:
    for acc in accounts:
        db.add(models.Account(**acc.model_dump()))
    db.commit()

    rows: dict[str, models.Transaction] = {}
    for t in transactions:
        row = models.Transaction(
            transaction_ref=t.transaction_ref,
            from_account=t.from_account,
            to_account=t.to_account,
            amount=Decimal(t.amount),
            currency=t.currency,
            status="RECEIVED",
            created_at=datetime.fromisoformat(t.created_at),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        rows[t.transaction_ref] = row
        service.run_detection(db, row)
    return rows


def _build_from_rule(
    *,
    scenario_id: str,
    category: str,
    description: str,
    transactions: list[TransactionFixture],
    accounts: list[AccountFixture],
    primary_ref: str,
    rule_code: str,
    expected_status: str = "PENDING_REVIEW",
    expected_facts: list[str] | None = None,
    allowed_transaction_refs: list[str] | None = None,
    allowed_accounts: list[str] | None = None,
    expected_uncertainty_keywords: list[str] | None = None,
    forbidden_claim_keywords: list[str] | None = None,
    notes: str = "",
    drop_transaction_refs: set[str] | None = None,
) -> ScenarioSpec:
    """Runs the fixtures through the real detection engine in an isolated
    in-memory DB, records whatever alert actually came out, then (if asked)
    drops some non-primary fixtures from what gets *stored* -- reproducing
    a "the alert references data that's since disappeared" scenario while
    keeping the alert's evidence exactly as the engine really produced it.
    """
    db, engine = _fresh_session()
    try:
        rows = _insert_and_detect(db, transactions, accounts)
        primary = rows[primary_ref]
        alert = (
            db.query(models.Alert)
            .filter_by(transaction_id=primary.id, rule_code=rule_code)
            .one_or_none()
        )
        if alert is None:
            raise RuntimeError(
                f"Generator bug in scenario {scenario_id!r}: expected "
                f"{rule_code} to fire on {primary_ref}, but it didn't."
            )
        alert_evidence = dict(alert.evidence)
        alert_description = alert.description
        severity = alert.severity
    finally:
        db.close()
        engine.dispose()

    stored_transactions = transactions
    if drop_transaction_refs:
        stored_transactions = [
            t for t in transactions if t.transaction_ref not in drop_transaction_refs
        ]

    return ScenarioSpec(
        id=scenario_id,
        category=category,
        description=description,
        transactions=stored_transactions,
        accounts=accounts,
        primary_transaction_ref=primary_ref,
        rule_code=rule_code,
        severity=severity,
        alert_description=alert_description,
        alert_evidence=alert_evidence,
        expected_status=expected_status,
        expected_facts=expected_facts or [],
        allowed_transaction_refs=allowed_transaction_refs or [primary_ref],
        allowed_accounts=allowed_accounts or [],
        expected_uncertainty_keywords=expected_uncertainty_keywords or [],
        forbidden_claim_keywords=forbidden_claim_keywords or list(FORBIDDEN_FRAUD_CLAIMS),
        notes=notes,
    )


# --- category 1: high-value transfer ---


def gen_high_value_transfer(
    rng: random.Random, index: int, *, force_register: bool | None = None
) -> ScenarioSpec:
    sid = f"high_value_transfer-{index:03d}"
    amount = (HIGH_VALUE_THRESHOLD + Decimal(rng.randint(1, 5_000_000))).quantize(
        Decimal("0.01")
    )
    currency = rng.choice(["INR", "USD", "EUR"])
    from_acc = f"ACC-HV-{index:03d}-SRC"
    to_acc = f"ACC-HV-{index:03d}-DST"
    register = force_register if force_register is not None else rng.random() < 0.5
    accounts = (
        [
            AccountFixture(account_number=from_acc, owner_name=f"Owner {index}A"),
            AccountFixture(account_number=to_acc, owner_name=f"Owner {index}B"),
        ]
        if register
        else []
    )
    txn_ref = f"TXN-HV-{index:03d}"
    created_at = (BASE_TIME + timedelta(minutes=index)).isoformat()
    transactions = [
        TransactionFixture(
            transaction_ref=txn_ref,
            from_account=from_acc,
            to_account=to_acc,
            amount=str(amount),
            currency=currency,
            created_at=created_at,
        )
    ]
    return _build_from_rule(
        scenario_id=sid,
        category="high_value_transfer",
        description=(
            f"A single transfer of {amount} {currency} exceeds the "
            "high-value threshold."
        ),
        transactions=transactions,
        accounts=accounts,
        primary_ref=txn_ref,
        rule_code="TXN_HIGH_VALUE",
        expected_facts=[str(amount), currency],
        allowed_transaction_refs=[txn_ref],
        allowed_accounts=[from_acc, to_acc],
        expected_uncertainty_keywords=[] if register else ["account registry"],
        notes="Expect the amount and currency cited as confirmed facts.",
    )


# --- category 2: high transaction velocity ---


def gen_high_velocity(
    rng: random.Random,
    index: int,
    *,
    force_register: bool | None = None,
    drop_count: int = 0,
) -> ScenarioSpec:
    sid = f"high_velocity-{index:03d}"
    count = VELOCITY_MAX_TRANSFERS + rng.randint(0, 3)
    from_acc = f"ACC-VEL-{index:03d}"
    base = BASE_TIME + timedelta(hours=index)
    spacing = VELOCITY_WINDOW_SECONDS // (count + 1)

    transactions = []
    for i in range(count):
        dest = f"ACC-VEL-{index:03d}-DST-{i}"
        ref = f"TXN-VEL-{index:03d}-{i}"
        created_at = (base + timedelta(seconds=spacing * i)).isoformat()
        amount = Decimal(rng.randint(100, 5000)).quantize(Decimal("0.01"))
        transactions.append(
            TransactionFixture(
                transaction_ref=ref,
                from_account=from_acc,
                to_account=dest,
                amount=str(amount),
                created_at=created_at,
            )
        )

    primary_ref = transactions[-1].transaction_ref
    all_refs = [t.transaction_ref for t in transactions]
    all_accounts = [from_acc] + [t.to_account for t in transactions]

    register = force_register if force_register is not None else rng.random() < 0.5
    accounts = (
        [AccountFixture(account_number=from_acc, owner_name=f"Owner {index}")]
        if register
        else []
    )

    non_primary_refs = [r for r in all_refs if r != primary_ref]
    drop_refs = (
        set(rng.sample(non_primary_refs, min(drop_count, len(non_primary_refs))))
        if drop_count
        else set()
    )

    uncertainty_kw = [] if register else ["account registry"]
    if drop_refs:
        uncertainty_kw.append("not found in the database")

    return _build_from_rule(
        scenario_id=sid,
        category="high_velocity",
        description=f"{count} transfers from {from_acc} within the velocity window.",
        transactions=transactions,
        accounts=accounts,
        primary_ref=primary_ref,
        rule_code="TXN_VELOCITY",
        expected_facts=[str(count), str(VELOCITY_WINDOW_SECONDS)],
        allowed_transaction_refs=all_refs,
        allowed_accounts=all_accounts,
        expected_uncertainty_keywords=uncertainty_kw,
        notes="Expect the transfer count and time window cited as confirmed facts.",
        drop_transaction_refs=drop_refs,
    )


# --- category 3: circular transaction flow ---


def gen_circular_flow(
    rng: random.Random,
    index: int,
    *,
    force_register: bool | None = None,
    drop_count: int = 0,
) -> ScenarioSpec:
    sid = f"circular_flow-{index:03d}"
    hops = rng.randint(CIRCULAR_MIN_HOPS, CIRCULAR_MAX_HOPS)
    accounts_in_cycle = [f"ACC-CYC-{index:03d}-{chr(65 + i)}" for i in range(hops)]
    base = BASE_TIME + timedelta(hours=1000 + index)
    layering = rng.random() < 0.5
    amount = Decimal(rng.randint(1000, 50000)).quantize(Decimal("0.01"))

    transactions = []
    for i in range(hops):
        src = accounts_in_cycle[i]
        dst = accounts_in_cycle[(i + 1) % hops]
        ref = f"TXN-CYC-{index:03d}-{i}"
        created_at = (base + timedelta(seconds=30 * i)).isoformat()
        hop_amount = amount * (Decimal("0.98") ** i) if layering else amount
        hop_amount = hop_amount.quantize(Decimal("0.01"))
        transactions.append(
            TransactionFixture(
                transaction_ref=ref,
                from_account=src,
                to_account=dst,
                amount=str(hop_amount),
                created_at=created_at,
            )
        )

    primary_ref = transactions[-1].transaction_ref  # the closing hop
    all_refs = [t.transaction_ref for t in transactions]

    register = force_register if force_register is not None else rng.random() < 0.5
    accounts = (
        [
            AccountFixture(account_number=a, owner_name=f"Owner {index}-{a[-1]}")
            for a in accounts_in_cycle
        ]
        if register
        else []
    )

    non_primary_refs = [r for r in all_refs if r != primary_ref]
    drop_refs = (
        set(rng.sample(non_primary_refs, min(drop_count, len(non_primary_refs))))
        if drop_count
        else set()
    )

    uncertainty_kw = [] if register else ["account registry"]
    if drop_refs:
        uncertainty_kw.append("not found in the database")

    return _build_from_rule(
        scenario_id=sid,
        category="circular_flow",
        description=f"A {hops}-hop circular flow returning to the origin account.",
        transactions=transactions,
        accounts=accounts,
        primary_ref=primary_ref,
        rule_code="TXN_CIRCULAR_FLOW",
        expected_facts=list(accounts_in_cycle),
        allowed_transaction_refs=all_refs,
        allowed_accounts=accounts_in_cycle,
        expected_uncertainty_keywords=uncertainty_kw,
        notes="Expect the full account chain cited, in order.",
        drop_transaction_refs=drop_refs,
    )


# --- category 4: missing account records ---


def gen_missing_account_records(rng: random.Random, index: int) -> ScenarioSpec:
    kind = rng.choice(["high_value", "velocity", "circular"])
    if kind == "high_value":
        base = gen_high_value_transfer(rng, 7000 + index, force_register=False)
    elif kind == "velocity":
        base = gen_high_velocity(rng, 7000 + index, force_register=False)
    else:
        base = gen_circular_flow(rng, 7000 + index, force_register=False)

    return base.model_copy(
        update={
            "id": f"missing_account_records-{index:03d}",
            "category": "missing_account_records",
            "description": (
                "None of the accounts involved have an entry in the account "
                "registry; the report must explicitly flag this rather than "
                "assume they're legitimate or fraudulent."
            ),
            "expected_uncertainty_keywords": ["account registry"],
            "notes": "Every account referenced is unregistered by design.",
        }
    )


# --- category 5: legitimate unusual activity ---


def gen_legitimate_unusual_activity(rng: random.Random, index: int) -> ScenarioSpec:
    sid = f"legitimate_unusual_activity-{index:03d}"
    owner = f"Owner {index}"
    use_velocity = rng.random() < 0.5

    if use_velocity:
        count = VELOCITY_MAX_TRANSFERS + rng.randint(0, 2)
        from_acc = f"ACC-LEGIT-{index:03d}-SRC"
        dest = f"ACC-LEGIT-{index:03d}-DST"
        base = BASE_TIME + timedelta(hours=2000 + index)
        spacing = VELOCITY_WINDOW_SECONDS // (count + 1)
        transactions = [
            TransactionFixture(
                transaction_ref=f"TXN-LEGIT-{index:03d}-{i}",
                from_account=from_acc,
                to_account=dest,
                amount=str(Decimal(rng.randint(1000, 10000)).quantize(Decimal("0.01"))),
                created_at=(base + timedelta(seconds=spacing * i)).isoformat(),
            )
            for i in range(count)
        ]
        primary_ref = transactions[-1].transaction_ref
        rule_code = "TXN_VELOCITY"
        all_refs = [t.transaction_ref for t in transactions]
        allowed_accounts = [from_acc, dest]
        accounts = [
            AccountFixture(account_number=from_acc, owner_name=owner),
            AccountFixture(account_number=dest, owner_name=owner),
        ]
        expected_facts = [str(count)]
        description = (
            f"{count} rapid transfers, all between accounts owned by the "
            "same registered customer (consistent with an automated sweep)."
        )
    else:
        amount = (HIGH_VALUE_THRESHOLD + Decimal(rng.randint(1, 1_000_000))).quantize(
            Decimal("0.01")
        )
        from_acc = f"ACC-LEGIT-{index:03d}-SRC"
        to_acc = f"ACC-LEGIT-{index:03d}-DST"
        ref = f"TXN-LEGIT-{index:03d}"
        transactions = [
            TransactionFixture(
                transaction_ref=ref,
                from_account=from_acc,
                to_account=to_acc,
                amount=str(amount),
                created_at=(BASE_TIME + timedelta(hours=3000 + index)).isoformat(),
            )
        ]
        primary_ref = ref
        rule_code = "TXN_HIGH_VALUE"
        all_refs = [ref]
        allowed_accounts = [from_acc, to_acc]
        accounts = [
            AccountFixture(account_number=from_acc, owner_name=owner),
            AccountFixture(account_number=to_acc, owner_name=owner),
        ]
        expected_facts = [str(amount)]
        description = (
            f"A high-value transfer of {amount} between two registered "
            "accounts owned by the same customer (consistent with a "
            "legitimate internal transfer)."
        )

    return _build_from_rule(
        scenario_id=sid,
        category="legitimate_unusual_activity",
        description=description,
        transactions=transactions,
        accounts=accounts,
        primary_ref=primary_ref,
        rule_code=rule_code,
        expected_facts=expected_facts,
        allowed_transaction_refs=all_refs,
        allowed_accounts=allowed_accounts,
        expected_uncertainty_keywords=[],
        forbidden_claim_keywords=list(FORBIDDEN_FRAUD_CLAIMS),
        notes=(
            "Both accounts share the same registered owner. The report "
            "should treat fraud as a hypothesis at most, never a confirmed "
            "fact. forbidden_claim_keywords catches the worst case "
            "automatically; subtler hedging quality needs an LLM-judge or "
            "human spot check in Phase 2."
        ),
    )


# --- category 6: conflicting or incomplete evidence ---


def gen_conflicting_incomplete_evidence(rng: random.Random, index: int) -> ScenarioSpec:
    kind = rng.choice(["velocity", "circular"])
    drop_count = rng.randint(1, 2)
    if kind == "velocity":
        base = gen_high_velocity(rng, 7500 + index, drop_count=drop_count)
    else:
        base = gen_circular_flow(rng, 7500 + index, drop_count=drop_count)

    return base.model_copy(
        update={
            "id": f"conflicting_incomplete_evidence-{index:03d}",
            "category": "conflicting_incomplete_evidence",
            "description": (
                "The alert's own evidence references transactions that no "
                "longer exist in the database; the report must flag the "
                "gap instead of inventing what they would have shown."
            ),
            "notes": (
                "One or more referenced transactions were deliberately "
                "removed from the stored fixtures after detection ran, "
                "simulating a data-retention or deletion gap."
            ),
        }
    )


# --- category 7: invalid / unsupported citation (system resilience) ---


def gen_invalid_citation(rng: random.Random, index: int) -> ScenarioSpec:
    base = gen_high_value_transfer(rng, 8000 + index)
    fake_ref = f"TXN-FAKE-{index:03d}"
    poisoned_response = {
        "summary": "Fabricated summary citing a non-existent transaction.",
        "confirmed_facts": [f"Reference {fake_ref} shows a related transfer."],
        "hypotheses": [],
        "uncertainties": [],
        "recommended_checks": [],
        "cited_transaction_refs": [base.primary_transaction_ref, fake_ref],
        "cited_accounts": list(base.allowed_accounts),
    }
    return base.model_copy(
        update={
            "id": f"invalid_citation-{index:03d}",
            "category": "invalid_citation",
            "description": (
                "A model response cites a transaction reference absent "
                "from the retrieved evidence; the system must reject it as "
                "a probable hallucination rather than persist it."
            ),
            "simulated_llm_response": poisoned_response,
            "expected_status": "FAILED",
            "expected_facts": [],
            "expected_uncertainty_keywords": [],
            "notes": (
                f"Grounding check must reject the fabricated reference "
                f"'{fake_ref}' and mark the report FAILED."
            ),
        }
    )


# --- category 8: model timeout or malformed output (system resilience) ---


def gen_model_failure(rng: random.Random, index: int) -> ScenarioSpec:
    base = gen_high_value_transfer(rng, 8500 + index)
    failure = FAILURE_MODES[index % len(FAILURE_MODES)]
    return base.model_copy(
        update={
            "id": f"model_failure-{index:03d}",
            "category": "model_failure",
            "description": f"The model fails with a simulated '{failure}' error.",
            "simulated_llm_failure": failure,
            "expected_status": "FAILED",
            "expected_facts": [],
            "expected_uncertainty_keywords": [],
            "notes": (
                f"Phase 2 harness should inject a '{failure}' failure "
                "instead of calling a real model, and confirm the "
                "investigation still produces a FAILED report rather than "
                "raising or hanging."
            ),
        }
    )


GENERATORS: dict[str, Callable[[random.Random, int], ScenarioSpec]] = {
    "high_value_transfer": gen_high_value_transfer,
    "high_velocity": gen_high_velocity,
    "circular_flow": gen_circular_flow,
    "missing_account_records": gen_missing_account_records,
    "legitimate_unusual_activity": gen_legitimate_unusual_activity,
    "conflicting_incomplete_evidence": gen_conflicting_incomplete_evidence,
    "invalid_citation": gen_invalid_citation,
    "model_failure": gen_model_failure,
}


def build_dataset(
    seed: int = SEED, per_category: int = SCENARIOS_PER_CATEGORY
) -> list[ScenarioSpec]:
    rng = random.Random(seed)
    scenarios: list[ScenarioSpec] = []
    for generator in GENERATORS.values():
        for i in range(per_category):
            scenarios.append(generator(rng, i))
    return scenarios


def write_dataset(path: Path = DATASET_PATH, **kwargs) -> int:
    scenarios = build_dataset(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for scenario in scenarios:
            f.write(scenario.model_dump_json())
            f.write("\n")
    return len(scenarios)


def load_dataset(path: Path = DATASET_PATH) -> list[ScenarioSpec]:
    scenarios = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                scenarios.append(ScenarioSpec.model_validate_json(line))
    return scenarios


if __name__ == "__main__":
    count = write_dataset()
    print(f"Wrote {count} scenarios to {DATASET_PATH}")
