"""Phase 2v: attention precision.

These thresholds were tuned against a real inbox (259 messages / 33
flagged), so the tests encode what measurement actually showed - including
the two hypotheses that failed and the false negative that measurement
caught.
"""

import pytest

from app.services.mail_signals import (
    extract_address,
    has_high_signal_subject,
    is_automated_sender,
    looks_like_bulk,
    noise_reason,
    sender_counts,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"Henrietta F. | Candidate Selection" <alert@jobrapidoalert.com>', "alert@jobrapidoalert.com"),
        ("Unstop <noreply@emails.unstop.com>", "noreply@emails.unstop.com"),
        ("plain@example.com", "plain@example.com"),
        ("No address here", None),
        (None, None),
    ],
)
def test_extract_address(raw, expected):
    assert extract_address(raw) == expected


@pytest.mark.parametrize(
    "sender",
    [
        "Unstop <noreply@emails.unstop.com>",
        "LinkedIn <messages-noreply@linkedin.com>",
        "<alert@jobrapidoalert.com>",
        "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
        "Unstop Events <updates@unstop.email>",
        "<do-not-reply@example.com>",
    ],
)
def test_automated_senders_are_recognised(sender):
    assert is_automated_sender(sender) is True


@pytest.mark.parametrize(
    "sender",
    [
        "Priya Raman <priya@acmecorp.com>",
        "Hostinger <team@info.hostinger.com>",  # bulk-ish, but not an automated local-part
        "Abekus <hello@abekus.co>",
        # A real person at a company whose domain merely contains "alert" -
        # matching substrings anywhere would misclassify this.
        "Dana <dana@alerting-systems.com>",
    ],
)
def test_human_looking_senders_are_not_flagged_as_automated(sender):
    assert is_automated_sender(sender) is False


def test_unsubscribe_header_marks_bulk():
    assert looks_like_bulk({"from": "News <hi@news.example.com>", "is_bulk": True}) is True


def test_messages_ingested_before_this_phase_fall_back_to_sender_heuristic():
    """Old rows have no `is_bulk` key at all. They must degrade to the
    previous behavior, not be silently reclassified as clean."""
    assert looks_like_bulk({"from": "Unstop <noreply@emails.unstop.com>"}) is True
    assert looks_like_bulk({"from": "Priya <priya@acme.com>"}) is False


def test_repetition_is_the_strongest_noise_signal():
    """Measured: 5x abekus, 4x codebenders, 4x unstop in one week. A person
    doesn't send you the same thing five times."""
    payloads = [{"from": "Abekus <hello@abekus.co>", "subject": f"Job {i}"} for i in range(5)]
    counts = sender_counts(payloads)
    assert noise_reason(payloads[0], counts) == "5 messages from this sender this week"


def test_occasional_sender_is_not_noise():
    payloads = [{"from": "Priya <priya@acme.com>", "subject": "Contract question"}]
    assert noise_reason(payloads[0], sender_counts(payloads)) is None


def test_high_signal_subject_rescues_from_repetition():
    """The false negative measurement caught: a real interview invite from a
    job board that had sent 9 messages that week."""
    payloads = [{"from": "Internshala <student@internshala.com>", "subject": f"Job listing {i}"} for i in range(9)]
    invite = {"from": "Internshala <student@internshala.com>", "subject": "Interview Invite from Planys Technologies"}
    counts = sender_counts(payloads + [invite])

    assert noise_reason(payloads[0], counts) is not None  # ordinary listings stay filtered
    assert noise_reason(invite, counts) is None  # the invite survives


def test_high_signal_rescue_does_not_rescue_marketing_language():
    """The phrase list names commitments, not enthusiasm - otherwise it
    becomes a loophole any marketer can walk through."""
    for subject in ["Immediate Hiring - Apply Now!", "Last Chance to Book Buses", "50% off this week only"]:
        assert has_high_signal_subject({"subject": subject}) is False


def test_high_signal_rescue_does_not_bypass_a_mailing_list_blast():
    """Volume isn't why we distrust list mail, so the rescue must not
    override an explicit unsubscribe header."""
    blast = {"from": "News <hi@news.example.com>", "subject": "Invoice attached", "is_bulk": True}
    assert noise_reason(blast, {}) == "bulk mailing list"


@pytest.mark.parametrize(
    "subject",
    ["Interview Invite from Acme", "Your invoice is ready", "Your domain has expired", "Action required on your account"],
)
def test_high_signal_phrases_match_real_commitments(subject):
    assert has_high_signal_subject({"subject": subject}) is True
