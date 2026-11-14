import os
import secrets

os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_lapro.db")
os.environ.setdefault("OWNER_EMAIL", "owner@example.com")
os.environ.setdefault("FRONTEND_ORIGINS", "http://testserver")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def register(alias="testuser", email="test@example.com"):
    return client.post("/auth/register", json={
        "alias": alias, "email": email, "password": "a-very-long-test-password"
    })


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_login_and_profile():
    response = register("pytestuser", "pytest@example.com")
    assert response.status_code == 201
    login = client.post("/auth/login", json={
        "email": "pytest@example.com", "password": "a-very-long-test-password"
    })
    assert login.status_code == 200
    token = login.json()["access_token"]
    profile = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["alias"] == "pytestuser"


def test_post_comment_and_like():
    register("authorpytest", "authorpytest@example.com")
    author_login = client.post("/auth/login", json={
        "email": "authorpytest@example.com", "password": "a-very-long-test-password"
    }).json()
    author_headers = {"Authorization": f"Bearer {author_login['access_token']}"}
    post = client.post("/posts", headers=author_headers, json={
        "category": "thought", "body": "A test post"
    })
    assert post.status_code == 201
    post_id = post.json()["id"]

    register("readerpytest", "readerpytest@example.com")
    reader_login = client.post("/auth/login", json={
        "email": "readerpytest@example.com", "password": "a-very-long-test-password"
    }).json()
    reader_headers = {"Authorization": f"Bearer {reader_login['access_token']}"}
    comment = client.post(f"/posts/{post_id}/comments", headers=reader_headers,
                          json={"body": "A test reply"})
    assert comment.status_code == 201
    assert comment.json()["body"] == "A test reply"
    like = client.post(f"/posts/{post_id}/like", headers=reader_headers)
    assert like.status_code == 200
    assert like.json()["liked"] is True



def test_bgmi_news_is_staff_published_and_publicly_readable():
    owner = register("laproowner", "owner@example.com")
    assert owner.status_code == 201
    login = client.post("/auth/login", json={
        "email": "owner@example.com", "password": "a-very-long-test-password"
    })
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    published = client.post("/staff/bgmi/news", headers=headers, json={
        "title": "BGMI community test update",
        "body": "This is a test news item with a source link for the community.",
        "tag": "Community",
        "source_url": "https://example.com/update"
    })
    assert published.status_code == 201
    feed = client.get("/bgmi/news")
    assert feed.status_code == 200
    assert any(item["title"] == "BGMI community test update" for item in feed.json())

def test_support_ticket_lifecycle_and_resolution_notification():
    user_response = register("supportuser", "supportuser@example.com")
    assert user_response.status_code == 201
    user_login = client.post("/auth/login", json={
        "email": "supportuser@example.com", "password": "a-very-long-test-password"
    }).json()
    user_headers = {"Authorization": f"Bearer {user_login['access_token']}"}
    created = client.post("/support/tickets", headers=user_headers, json={
        "category": "bug",
        "subject": "Composer button does not respond",
        "details": "The publish button does not respond on my mobile browser."
    })
    assert created.status_code == 201
    ticket_id = created.json()["id"]
    assert created.json()["status"] == "open"

    owner_login = client.post("/auth/login", json={
        "email": "owner@example.com", "password": "a-very-long-test-password"
    }).json()
    owner_headers = {"Authorization": f"Bearer {owner_login['access_token']}"}
    queue = client.get("/staff/support/tickets?status=open", headers=owner_headers)
    assert queue.status_code == 200
    assert any(item["id"] == ticket_id for item in queue.json())

    resolved = client.patch(f"/staff/support/tickets/{ticket_id}", headers=owner_headers, json={
        "status": "resolved", "admin_reply": "Fixed in the latest update."
    })
    assert resolved.status_code == 200
    mine = client.get("/support/tickets", headers=user_headers)
    assert mine.status_code == 200
    assert mine.json()[0]["status"] == "resolved"
    notices = client.get("/notifications", headers=user_headers)
    assert notices.status_code == 200
    assert any(item["kind"] == "support_resolved" for item in notices.json())
