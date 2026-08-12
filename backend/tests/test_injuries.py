import unittest

from app.services.injuries import InjuryAnalyzer


class InjuryAnalyzerTests(unittest.TestCase):
    def test_returns_expected_structure_and_prioritizes_key_players(self):
        # Supply a fixed injury list so the test is independent of the live provider
        analyzer = InjuryAnalyzer(injuries=InjuryAnalyzer._mock_injuries(None))
        result = analyzer.analyze()

        self.assertIn("injuryScore", result)
        self.assertIn("offensiveImpact", result)
        self.assertIn("defensiveImpact", result)
        self.assertIn("specialTeamsImpact", result)
        self.assertIn("pointAdjustment", result)
        self.assertIn("keyPlayers", result)
        self.assertIn("summary", result)

        self.assertGreater(result["injuryScore"], 0)
        self.assertLessEqual(result["injuryScore"], 100)

        key_players = [player["player"] for player in result["keyPlayers"]]
        self.assertIn("Josh Allen", key_players)
        self.assertIn("Trent Williams", key_players)


if __name__ == "__main__":
    unittest.main()
