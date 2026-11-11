"""The transport under the notices this app owes people who have no account.

What is sent, and in whose words, is proven where the notice is triggered. What
this file proves is how it crosses the network: a notice must not travel in the
clear when the relay can encrypt it, and a password must never travel at all
unless the relay proved its name first.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from conftest import (
    eml_files,
    read_msg,
    use_example_data,
    use_outbox,
    write_config,
    write_secrets,
)


class FakeRelay:
    """A relay that records what a client did to it, in order."""

    offers_starttls: ClassVar[bool] = True
    steps: ClassVar[list[str]] = []

    refused: ClassVar[dict[str, tuple[int, bytes]]] = {}
    fails: ClassVar[str] = ""  # a reason the connection itself does not come up

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        FakeRelay.steps = [f"connect {host}:{port} timeout={timeout}"]
        self.greeted = False
        if FakeRelay.fails:
            raise TimeoutError(FakeRelay.fails)

    def __enter__(self) -> FakeRelay:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def ehlo(self) -> None:
        self.steps.append("ehlo")
        self.greeted = True

    def has_extn(self, name: str) -> bool:
        # Like `smtplib`: the feature list is empty until the greeting is answered.
        return self.greeted and name == "starttls" and self.offers_starttls

    def starttls(self, context: Any = None) -> None:
        self.steps.append(
            f"starttls verify={context.verify_mode.name} check={context.check_hostname}"
        )

    def login(self, user: str, password: str) -> None:
        self.steps.append(f"login {user}:{password}")

    def send_message(self, msg: Any) -> dict[str, tuple[int, bytes]]:
        # Like `smtplib`: a partial refusal is reported, not raised.
        self.steps.append(f"send {msg['To']}")
        return dict(FakeRelay.refused)


@pytest.fixture
def relay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> type[FakeRelay]:
    """A data dir whose `smtp.host` names a relay, with the fake standing in for it."""
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {"host": "relay.example.nl", "port": 587, "sender": "noreply@example.nl"}
    write_config(tmp_path, config)
    write_secrets(tmp_path, {"smtp_pass": "geheim"})

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", FakeRelay)
    FakeRelay.offers_starttls = True
    FakeRelay.refused = {}
    FakeRelay.fails = ""
    return FakeRelay


def _with_login(tmp_path: Path, user: str = "odas@example.nl") -> None:
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["smtp"] = {**config["smtp"], "user": user}
    write_config(tmp_path, config)


def test_a_notice_is_encrypted_whenever_the_relay_offers_it(relay: type[FakeRelay]) -> None:
    """No login is needed to deserve encryption: the notice names a person and a zaak."""
    from odas import mail

    assert mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps[2].startswith("starttls")
    assert relay.steps[3] == "send indiener@example.org"  # encrypted before the body


def test_a_relay_is_asked_to_prove_its_name(relay: type[FakeRelay]) -> None:
    """The default context of `starttls()` checks neither the chain nor the name."""
    from odas import mail

    mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps[2] == "starttls verify=CERT_REQUIRED check=True"


def test_a_password_is_never_sent_to_a_relay_that_did_not_prove_its_name(
    relay: type[FakeRelay], tmp_path: Path
) -> None:
    """A relay that cannot encrypt gets no credentials, and the notice is not sent."""
    _with_login(tmp_path)
    relay.offers_starttls = False

    from odas import mail

    with pytest.raises(mail.MailError, match="STARTTLS"):
        mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")
    assert relay.steps == ["connect relay.example.nl:587 timeout=10", "ehlo"]  # no login, no body


def test_a_relay_that_asks_for_a_login_gets_one_over_the_encrypted_connection(
    relay: type[FakeRelay], tmp_path: Path
) -> None:
    """The credentials live in `.app/secrets.yaml` and go out after STARTTLS, never before."""
    _with_login(tmp_path)

    from odas import mail

    assert mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps[2].startswith("starttls")
    assert relay.steps[3] == "login odas@example.nl:geheim"
    assert relay.steps[4] == "send indiener@example.org"


def test_a_relay_that_cannot_encrypt_still_carries_a_notice_that_needs_no_login(
    relay: type[FakeRelay],
) -> None:
    """An intake confirmation is not lost because the relay is old. Only a password is."""
    relay.offers_starttls = False

    from odas import mail

    assert mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps == [
        "connect relay.example.nl:587 timeout=10",
        "ehlo",
        "send indiener@example.org",
    ]


def test_a_relay_is_greeted_before_the_client_reads_what_it_offers(
    relay: type[FakeRelay],
) -> None:
    """A relay that offers STARTTLS is used, not skipped: it lists what it offers on EHLO."""
    from odas import mail

    assert mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps[1] == "ehlo"  # asking before greeting reads an empty list
    assert relay.steps[2].startswith("starttls")


def test_a_message_carries_a_date_and_an_identifier_of_the_sending_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receiver must not read a stamp of the relay where the sender's own belongs."""
    use_example_data("veenwacht", tmp_path, monkeypatch)
    outbox = use_outbox(tmp_path)

    from odas import mail

    assert mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    msg = read_msg(eml_files(outbox)[0])
    assert msg["Date"]
    assert msg["Message-ID"].endswith(
        "@hulpvraag.veenwacht.example.nl>"
    )  # the domain the From names


def test_a_relay_that_does_not_answer_is_named_in_the_error(relay: type[FakeRelay]) -> None:
    """A person reads why the message stayed: the machine that would not take it."""
    relay.fails = "timed out"

    from odas import mail

    with pytest.raises(mail.MailError, match=re.escape("relay.example.nl")):
        mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")


def test_a_relay_is_given_a_time_limit(relay: type[FakeRelay]) -> None:
    """A relay that never answers must not hold the request that asked for the mail."""
    from odas import mail

    mail.send(["indiener@example.org"], "Ontvangen", "Uw bericht is ontvangen.")

    assert relay.steps[0] == "connect relay.example.nl:587 timeout=10"


def test_a_recipient_the_relay_refuses_makes_the_whole_send_fail(
    relay: type[FakeRelay],
) -> None:
    """`smtplib` reports a partly refused message instead of raising. Here it is loud."""
    relay.refused = {"weg@example.org": (550, b"no such user")}

    from odas import mail

    with pytest.raises(mail.MailError, match=re.escape("weg@example.org")):
        mail.send(["indiener@example.org", "weg@example.org"], "Ontvangen", "Tekst.")


def test_a_data_dir_with_no_transport_says_so() -> None:
    """An empty `smtp.host` cannot carry a message a person asked for."""
    from odas import mail

    with pytest.raises(mail.MailError, match="mailtransport"):
        mail.send(["indiener@example.org"], "Ontvangen", "Tekst.")
