"""R2 via boto3. The Stubber validates every call against botocore's S3 model, so parameter
names such as IfNoneMatch and IfMatch are checked against the real API definition."""

import io

import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from nearpost.store.base import PreconditionFailedError
from nearpost.store.r2 import R2Store, make_client


@pytest.fixture
def stubbed():
    client = make_client(account_id="acct", access_key_id="id", secret_access_key="secret")
    with Stubber(client) as stubber:
        yield R2Store(client, "nearpost-recorder"), stubber
        stubber.assert_no_pending_responses()


def test_client_targets_the_account_endpoint():
    client = make_client(account_id="acct", access_key_id="id", secret_access_key="secret")
    assert client.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"


def test_get_returns_bytes_and_unquoted_etag(stubbed):
    store, stubber = stubbed
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"{}"), 2), "ETag": '"abc"'},
        {"Bucket": "nearpost-recorder", "Key": "state/status.json"},
    )
    blob = store.get("state/status.json")
    assert (blob.data, blob.etag) == (b"{}", "abc")


def test_get_missing_key_returns_none(stubbed):
    store, stubber = stubbed
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    assert store.get("nope.json") is None


def test_create_only_put_sends_if_none_match(stubbed):
    store, stubber = stubbed
    stubber.add_response(
        "put_object",
        {"ETag": '"e1"'},
        {
            "Bucket": "nearpost-recorder",
            "Key": "ledger/blocks/000000.json",
            "Body": b"x",
            "ContentType": "application/json",
            "IfNoneMatch": "*",
        },
    )
    assert store.put("ledger/blocks/000000.json", b"x", if_none_match=True) == "e1"


def test_conditional_update_sends_if_match_with_quotes(stubbed):
    store, stubber = stubbed
    stubber.add_response(
        "put_object",
        {"ETag": '"e2"'},
        {"Bucket": "nearpost-recorder", "Key": "ledger/index.json", "Body": ANY, "ContentType": ANY, "IfMatch": '"e1"'},
    )
    assert store.put("ledger/index.json", b"x", if_match="e1") == "e2"


@pytest.mark.parametrize(("code", "status"), [("PreconditionFailed", 412), ("ConditionalRequestConflict", 409)])
def test_lost_conditional_writes_become_precondition_failures(stubbed, code, status):
    store, stubber = stubbed
    stubber.add_client_error("put_object", service_error_code=code, http_status_code=status)
    with pytest.raises(PreconditionFailedError):
        store.put("ledger/blocks/000000.json", b"x", if_none_match=True)


def test_other_errors_propagate(stubbed):
    store, stubber = stubbed
    stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(Exception, match="AccessDenied"):
        store.put("state/status.json", b"x")


def test_list_keys_pages_through_results(stubbed):
    store, stubber = stubbed
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "ledger/blocks/000001.json"}], "IsTruncated": True, "NextContinuationToken": "t"},
        {"Bucket": "nearpost-recorder", "Prefix": "ledger/blocks/", "StartAfter": "ledger/blocks/000000.json"},
    )
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "ledger/blocks/000002.json"}], "IsTruncated": False},
        {
            "Bucket": "nearpost-recorder",
            "Prefix": "ledger/blocks/",
            "StartAfter": "ledger/blocks/000000.json",
            "ContinuationToken": "t",
        },
    )
    assert store.list_keys("ledger/blocks/", start_after="ledger/blocks/000000.json") == [
        "ledger/blocks/000001.json",
        "ledger/blocks/000002.json",
    ]
