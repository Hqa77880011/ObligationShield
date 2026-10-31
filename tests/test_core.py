import unittest

from obligationshield import core


class GameTests(unittest.TestCase):
    def test_failure_contract_violation_cannot_receive_winning_strategy(self):
        jobs = [dict(id="a", work=1, deadline=2, handlers=["audit"])]
        with self.assertRaisesRegex(ValueError, "failure state"):
            core.winning(jobs, 2, ["audit"], 1, streak=(2,))
        self.assertTrue(core.winning(jobs, 2, ["audit"], 1, streak=(1,))[0])

    def test_false_safe_denominator_is_admitted_states(self):
        case = {
            "jobs": [],
            "horizon": 1,
            "handlers": ["audit"],
            "max_consecutive_failures": 0,
        }
        metrics = core.score(case, {"admitted": False, "states": 0})
        self.assertIsNone(metrics["false_safe"])

    def test_base_denial_cannot_release_even_with_no_debt(self):
        case = {
            "jobs": [],
            "horizon": 1,
            "handlers": ["audit"],
            "max_consecutive_failures": 0,
            "existing_count": 0,
            "base_permit": False,
        }
        self.assertFalse(core.run_case(case, "obligationshield")["admitted"])

    def test_quantifier_order_and_conservative_deadline(self):
        jobs = [
            dict(id=str(i), work=1, deadline=3, handlers=["audit"]) for i in range(2)
        ]
        self.assertTrue(all(core.winning([job], 4, ["audit"], 1)[0] for job in jobs))
        self.assertFalse(core.winning(jobs, 4, ["audit"], 1)[0])
        for deadline in (2, 3, 4):
            case = {
                "jobs": [{**job, "deadline": deadline} for job in jobs],
                "horizon": 4,
                "handlers": ["audit"],
                "max_consecutive_failures": 1,
                "existing_count": 0,
            }
            self.assertEqual(
                core.run_case(case, "exact_game")["admitted"], core.oracle(case)
            )
            if core.run_case(case, "obligationshield")["admitted"]:
                self.assertTrue(core.oracle(case))

    def test_quotient_retains_multiplicity_and_matches_exact_game(self):
        jobs = [
            dict(id=str(i), work=1, deadline=4, handlers=["audit"]) for i in range(3)
        ]
        for maximum in (0, 1):
            for count in (1, 2, 3):
                case = dict(
                    jobs=jobs[:count],
                    horizon=4,
                    handlers=["audit"],
                    max_consecutive_failures=maximum,
                    existing_count=0,
                )
                self.assertEqual(
                    core.run_case(case, "quotient_game")["admitted"], core.oracle(case)
                )
                full = core.winning(case["jobs"], 4, ["audit"], maximum)[0]
                reduced = core.winning(
                    case["jobs"], 4, ["audit"], maximum, quotient=True, antichains=True
                )[0]
                self.assertEqual(full, reduced)


if __name__ == "__main__":
    unittest.main()
