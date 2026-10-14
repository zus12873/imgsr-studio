from imgsr.clientip import parse_networks, resolve_client_ip

TRUSTED = parse_networks("127.0.0.1,172.16.0.0/12")
XFF = "X-Forwarded-For"


def test_untrusted_peer_cannot_spoof():
    assert resolve_client_ip("8.8.8.8", {XFF: "1.1.1.1"}, XFF, TRUSTED) == "8.8.8.8"


def test_trusted_proxy_header_is_used():
    assert resolve_client_ip("127.0.0.1", {XFF: "1.2.3.4"}, XFF, TRUSTED) == "1.2.3.4"


def test_rightmost_untrusted_address_wins():
    headers = {XFF: "6.6.6.6, 1.2.3.4, 172.18.0.5"}
    assert resolve_client_ip("172.18.0.1", headers, XFF, TRUSTED) == "1.2.3.4"


def test_garbage_or_missing_header_falls_back_to_peer():
    assert resolve_client_ip("127.0.0.1", {XFF: "not-an-ip"}, XFF, TRUSTED) == "127.0.0.1"
    assert resolve_client_ip("127.0.0.1", {}, XFF, TRUSTED) == "127.0.0.1"


def test_cf_connecting_ip():
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    assert resolve_client_ip("127.0.0.1", headers, "CF-Connecting-IP", TRUSTED) == "203.0.113.9"


def test_non_ip_peer_is_untrusted():
    assert resolve_client_ip("testclient", {XFF: "1.1.1.1"}, XFF, TRUSTED) == "testclient"
