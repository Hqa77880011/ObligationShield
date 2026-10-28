"""Hand-defined finite-state checks, without campaigns or external handlers."""

import copy
import unittest

from obligationshield.core import winning
from obligationshield.runtime import FiniteExecutor, Ledger, drive


def audits(deadline=4):
    return [
        dict(id=str(i), work=1, deadline=deadline, handlers=["audit"], predecessors=[])
        for i in range(2)
    ]


class RuntimeTests(unittest.TestCase):
    def model(self, handlers=("audit",), maximum=1, failures=None, existing=()):
        ledger = Ledger(":memory:", 4, list(handlers), maximum, existing=existing)
        executor = FiniteExecutor(":memory:", failures or {})
        self.addCleanup(ledger.close)
        self.addCleanup(executor.close)
        return ledger, executor

    def test_shared_debt_counterexample_rejects_without_release(self):
        jobs = audits(3)
        self.assertTrue(all(winning([job], 4, ["audit"])[0] for job in jobs))
        self.assertFalse(winning(jobs, 4, ["audit"])[0])
        ledger, _ = self.model(existing=jobs[:1])
        self.assertEqual(
            ledger.admit("second", jobs[1:], {"object": "record"}, True), "DENIED"
        )
        self.assertEqual(len(ledger.snapshot()["debt"]), 1)
        self.assertEqual(ledger.releases(), [])

    def test_winning_actions_drive_actual_model_effects_and_receipts(self):
        ledger, executor = self.model(failures={"0": ["audit"], "2": ["audit"]})
        jobs, release = audits(), {"object": "record"}
        self.assertEqual(ledger.admit("r", jobs, release, True), "ADMITTED")
        self.assertEqual(ledger.admit("r", jobs, release, True), "ADMITTED")
        state = drive(ledger, executor)
        self.assertEqual(state["tick"], 4)
        self.assertIsNone(state["frozen"])
        self.assertEqual([item["remaining"] for item in state["debt"]], [0, 0])
        controls = [
            item for item in state["outbox"] if item["command"]["kind"] == "handler"
        ]
        self.assertTrue(
            all(item["command"]["strategy"] == "winning" for item in controls)
        )
        effects = executor.db.execute("SELECT command FROM effects").fetchall()
        self.assertEqual(len(effects), 3)  # One release, two distinct audit effects.
        self.assertEqual(state, drive(ledger, executor))
        self.assertEqual(
            executor.db.execute("SELECT COUNT(*) FROM effects").fetchone()[0], 3
        )

    def test_missing_receipt_retains_debt_and_defers_admission(self):
        ledger, executor = self.model(handlers=("audit", "notify"), maximum=0)
        job = dict(id="j", work=2, deadline=1, handlers=["audit", "notify"])
        self.assertEqual(ledger.admit("r", [job], {}, True), "ADMITTED")
        commands = ledger.dispatch()
        receipt = executor.execute(commands[0])
        ledger.receipt(receipt, executor.verify)
        state = ledger.snapshot()
        self.assertEqual((state["tick"], state["debt"][0]["remaining"]), (0, 2))
        self.assertEqual(ledger.admit("new", [], {}, True), "DEFER")
        self.assertFalse(ledger.emit_release(ledger.releases()[0], executor))
        ledger.receipt(executor.execute(commands[1]), executor.verify)
        self.assertEqual(ledger.snapshot()["debt"][0]["remaining"], 0)
        ledger.receipt(receipt, executor.verify)
        self.assertEqual(ledger.snapshot()["tick"], 1)

    def test_unrecognized_and_forged_receipts_cannot_clear_debt(self):
        ledger, executor = self.model()
        ledger.admit("r", audits(), {}, True)
        command = ledger.dispatch()[0]
        forged = dict(
            command=command, success=True, effect_committed=True, mode="finite_model"
        )
        with self.assertRaisesRegex(ValueError, "trusted verifier"):
            ledger.receipt(forged, executor.verify)
        unknown = copy.deepcopy(command)
        unknown["id"] = "unrecognized"
        verified_but_unknown = executor.execute(unknown)
        with self.assertRaisesRegex(ValueError, "persisted command"):
            ledger.receipt(verified_but_unknown, executor.verify)
        self.assertEqual(
            [item["remaining"] for item in ledger.snapshot()["debt"]], [1, 1]
        )

    def test_assumption_failure_freezes_new_releases_and_recovers_debt(self):
        ledger, executor = self.model(maximum=0, failures={"0": ["audit"]})
        ledger.admit("r", audits(), {}, True)
        command = ledger.dispatch()[0]
        ledger.receipt(executor.execute(command), executor.verify)
        self.assertEqual(ledger.snapshot()["frozen"], "failure_contract")
        self.assertEqual(ledger.admit("later", [], {}, True), "DEFER")
        self.assertFalse(ledger.emit_release(ledger.releases()[0], executor))
        self.assertEqual(ledger.dispatch()[0]["strategy"], "recovery_edf")
        self.assertEqual(
            [item["remaining"] for item in drive(ledger, executor)["debt"]], [0, 0]
        )

    def test_predecessors_wait_for_authenticated_completion(self):
        ledger, executor = self.model(maximum=0)
        jobs = audits(2)
        jobs[1]["predecessors"] = ["0"]
        ledger.admit("r", jobs, {}, True)
        first = ledger.dispatch()[0]
        self.assertEqual(first["job"], "0")
        self.assertEqual(ledger.dispatch(), [first])
        ledger.receipt(executor.execute(first), executor.verify)
        second = ledger.dispatch()[0]
        self.assertEqual(second["job"], "1")
        self.assertEqual(second["origin"], "r")
        self.assertEqual(second["obligation"], jobs[1])

    def test_replay_argument_binding_and_validation_are_atomic(self):
        ledger, _ = self.model()
        ledger.admit("r", audits(), {}, True)
        before = ledger.snapshot()
        with self.assertRaisesRegex(ValueError, "different arguments"):
            ledger.admit("r", audits(), {"different": True}, True)
        invalid = [
            dict(
                id="bad",
                work=1,
                deadline=4,
                handlers=["audit"],
                predecessors=["unknown"],
            )
        ]
        with self.assertRaisesRegex(ValueError, "Unknown predecessor"):
            ledger.admit("invalid", invalid, {}, True)
        self.assertEqual(ledger.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
