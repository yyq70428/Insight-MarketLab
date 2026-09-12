from datetime import datetime, timezone, timedelta
from app.backend.services.historical_news import verify_article, interleave_verified
from app.backend.analysis.news_agent import validate_findings


def article(identifier, kind="stock", hours=-2):
    stamp=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()
    return {"id":identifier,"url":"https://example.com/a","type":kind,"publishedAt":stamp,"modifiedAt":stamp}


def test_article_after_cutoff_and_missing_timezone_are_rejected():
    cutoff=datetime.now(timezone.utc)
    assert verify_article(article("ok"), cutoff)[0]
    assert not verify_article(article("future", hours=2), cutoff)[0]
    bad=article("bad"); bad["publishedAt"]="2026-01-01T10:00:00"
    assert not verify_article(bad, cutoff)[0]


def test_news_identity_is_unique_and_type_cannot_be_reclassified():
    sources=[article("s1","stock"),article("m1","market")]
    findings=[{"sourceId":"s1","type":"stock"},{"sourceId":"s1","type":"stock"},{"sourceId":"m1","type":"stock"}]
    valid,limitations=validate_findings(findings,sources)
    assert len(valid)==1 and len(limitations)==2


def test_verified_news_is_interleaved():
    cutoff=datetime.now(timezone.utc)
    rows,_=interleave_verified([article("s1"),article("s2")],[article("m1","market"),article("m2","market")],cutoff)
    assert [row["type"] for row in rows]==["stock","market","stock","market"]
