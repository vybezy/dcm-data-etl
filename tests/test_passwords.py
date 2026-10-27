import hashlib
from unittest.mock import patch

import pytest

from services import passwords
from services.passwords import hash_password, password_problems, verify_password

FAST = 1000
GOOD = "Secret123!"


def test_hash_stores_algorithm_iterations_salt_and_hash():
    algorithm, iterations, salt, digest = hash_password(GOOD).split("$")

    assert algorithm == "pbkdf2_sha512"
    assert iterations == "210000"
    assert len(bytes.fromhex(salt)) == 16
    assert len(bytes.fromhex(digest)) == 64


def test_hash_matches_pbkdf2_sha512_with_the_stored_salt():
    _, iterations, salt, digest = hash_password(GOOD, iterations=FAST).split("$")

    expected = hashlib.pbkdf2_hmac("sha512", GOOD.encode(), bytes.fromhex(salt), int(iterations))
    assert digest == expected.hex()


def test_same_password_gets_a_different_hash_each_time():
    assert hash_password(GOOD, FAST) != hash_password(GOOD, FAST)


def test_password_is_never_in_the_hash():
    assert GOOD not in hash_password(GOOD, FAST)


@pytest.mark.parametrize("password", [
    "Secret123!",
    "A1!aaaaa",
    "Longer-Password_2026",
    "X9~`{}[]|\\:;\"'<>,.?/-_+=",
])
def test_good_passwords_have_no_problems(password):
    assert password_problems(password) == []


@pytest.mark.parametrize("password, problem", [
    ("Sh0rt!", "be at least 8 characters long"),
    ("secret123!", "contain a capital letter"),
    ("Secret!!!", "contain a digit"),
    ("Secret123", "contain a special character"),
    ("Secret 123!", "use only English letters, digits and symbols, without spaces"),
    ("Kωδικός123!", "use only English letters, digits and symbols, without spaces"),
    ("Pässword1!", "use only English letters, digits and symbols, without spaces"),
    ("Emoji123🙂", "use only English letters, digits and symbols, without spaces"),
    ("Aa1!" * 33, "be at most 128 characters long"),
])
def test_each_broken_rule_is_reported(password, problem):
    assert password_problems(password) == [problem]


def test_all_broken_rules_are_reported_together():
    assert password_problems("abc") == [
        "be at least 8 characters long",
        "contain a capital letter",
        "contain a digit",
        "contain a special character",
    ]


def test_hash_refuses_a_weak_password_with_every_reason():
    with pytest.raises(ValueError) as error:
        hash_password("secret", FAST)

    assert str(error.value) == (
        "password must be at least 8 characters long, contain a capital letter, "
        "contain a digit, contain a special character"
    )


@pytest.mark.parametrize("attempt, expected", [
    ("Correct-horse9", True),
    ("correct-horse9", False),
    ("Correct-horse9 ", False),
    ("", False),
])
def test_verify_password(attempt, expected):
    stored = hash_password("Correct-horse9", FAST)
    assert verify_password(attempt, stored) is expected


def test_a_non_english_attempt_simply_fails_at_login():
    stored = hash_password("Kodikos123!", FAST)
    assert verify_password("Κωδικός123!", stored) is False


def test_verify_uses_the_iterations_stored_with_the_hash():
    stored = hash_password(GOOD, iterations=FAST)

    with patch.object(passwords, "ITERATIONS", 5):
        assert verify_password(GOOD, stored) is True


@pytest.mark.parametrize("stored", [
    "",
    "not a hash",
    "pbkdf2_sha512$many$abcd$abcd",
    "pbkdf2_sha512$1000$zz$abcd",
    "pbkdf2_sha512$1000$abcd",
])
def test_broken_stored_hash_is_refused_not_crashed(stored):
    assert verify_password(GOOD, stored) is False


def test_other_algorithm_label_is_refused():
    stored = hash_password(GOOD, FAST).replace("pbkdf2_sha512", "md5", 1)
    assert verify_password(GOOD, stored) is False


def test_comparison_is_constant_time():
    stored = hash_password(GOOD, FAST)

    with patch("services.passwords.hmac.compare_digest", return_value=True) as compare:
        verify_password(GOOD, stored)

    compare.assert_called_once()
