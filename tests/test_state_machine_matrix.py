import unittest
from ai_engine.submission_generator import SubmissionGenerator, SubmissionBlock
from ai_engine.relevance_scorer import ScoringResult

class TestStateMachineMatrix(unittest.TestCase):
    def setUp(self):
        self.generator = SubmissionGenerator()
        self.study_config = {
            "study_id": "26052",
            "critical_date": "2019-10-28",
            "type": "invalidity",
            "requirements": [
                {"id": "1.1", "name": "Blades rotate around rotational axis", "text": "Blades rotate around rotational axis"},
                {"id": "1.2", "name": "Blade rotational axis offset", "text": "Blade rotational axis offset"}
            ]
        }

    def test_path_1_verified_date_real_match(self):
        """Path 1: Verified date + real requirement match + predicted_rank >= 2 -> READY_SUBMIT"""
        metadata = {"date_verified": True, "title": "Verified Blender Prior Art"}
        scoring = ScoringResult(
            predicted_rank=2,
            rank_confidence=0.92,
            in_scope_confidence="high",
            feature_importance={"date": 0.5},
            reasoning="Valid prior art",
            recommendation="SUBMIT"
        )
        selected_reqs = [{"id": "1.1", "text": "Blades rotate around rotational axis"}]
        
        tier = self.generator._classify_tier(scoring, selected_reqs, self.study_config)
        self.assertEqual(tier, "READY_SUBMIT")

    def test_path_2_unknown_date(self):
        """Path 2: Unknown date -> Structurally forced to HOLD"""
        metadata = {
            "date": "unknown",
            "date_verified": False,
            "requires_manual_review": True,
            "match_mode": "unknown_date",
            "title": "Undated Manual"
        }
        scoring = ScoringResult(
            predicted_rank=2,
            rank_confidence=0.90,
            in_scope_confidence="high",
            feature_importance={},
            reasoning="Undated",
            recommendation="SUBMIT"  # Scorer might suggest SUBMIT, but generator must force HOLD
        )
        submission = self.generator.generate_submission(metadata, [], scoring, self.study_config, "sample text")
        self.assertEqual(submission.tier, "HOLD")

    def test_path_3_fallback_requirement(self):
        """Path 3: Fallback requirement match -> Structurally forced to HOLD"""
        metadata = {
            "match_mode": "fallback",
            "requires_manual_review": True,
            "title": "Fallback Discovered Reference"
        }
        scoring = ScoringResult(
            predicted_rank=2,
            rank_confidence=0.50,
            in_scope_confidence="med",
            feature_importance={},
            reasoning="Fallback discovery",
            recommendation="HOLD"
        )
        submission = self.generator.generate_submission(metadata, [], scoring, self.study_config, "sample text")
        self.assertEqual(submission.tier, "HOLD")

    def test_path_4_no_match(self):
        """Path 4: No requirements matched -> Classified as SKIP"""
        metadata = {"date_verified": True, "title": "Irrelevant Document"}
        scoring = ScoringResult(
            predicted_rank=0,
            rank_confidence=0.20,
            in_scope_confidence="low",
            feature_importance={},
            reasoning="No match",
            recommendation="SKIP"
        )
        selected_reqs = []  # No requirements selected
        tier = self.generator._classify_tier(scoring, selected_reqs, self.study_config)
        self.assertEqual(tier, "SKIP")

if __name__ == "__main__":
    unittest.main()
