from app.backend.flow.learning import evaluate_shadow


def test_candidate_requires_minimum_samples_and_positive_lower_bound():
    assert not evaluate_shadow([0]*7,[1]*7)["passed"]
    assert evaluate_shadow([0]*8,[1]*8)["passed"]
    assert not evaluate_shadow([0]*8,[.05]*8)["passed"]


def test_news_candidate_requires_faithfulness():
    assert not evaluate_shadow([0]*8,[1]*8,faithfulness=.7)["passed"]
