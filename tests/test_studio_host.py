"""placemat studio --host: the address it listens on and the Host headers it accepts."""
from placemat import studio as studio_mod


class _S:
    allowed_hosts = studio_mod.Studio.allowed_hosts

    def __init__(self, host, port=8765):
        self.host, self.port = host, port


def test_default_accepts_only_localhost():
    assert _S("127.0.0.1").allowed_hosts() == {"127.0.0.1:8765", "localhost:8765"}


def test_listening_on_all_addresses_accepts_this_machines_lan_address():
    hosts = _S("0.0.0.0").allowed_hosts()
    assert {"127.0.0.1:8765", "localhost:8765"} <= hosts
    lan = studio_mod._url_host("0.0.0.0")
    assert "%s:8765" % lan in hosts


def test_a_named_address_is_accepted_as_itself():
    assert "192.0.2.10:8765" in _S("192.0.2.10").allowed_hosts()
