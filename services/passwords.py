import hashlib
import hmac
import re
import secrets

ALGORITHM = "pbkdf2_sha512"  # identifier for the hashing algorithm
ITERATIONS = 210_000  # number of repetitions for SHA-512 (OWASP's recommendation)
SALT_BYTES = 16  # number of bytes for the salt (helps with making every hash unique)

# password rules
MIN_LENGTH = 8
MAX_LENGTH = 128
ALLOWED_CHARACTERS = r"[\x21-\x7E]+"
REQUIRED_CHARACTERS = (
    (r"[A-Z]", "a capital letter"),
    (r"[0-9]", "a digit"),
    (r"[^A-Za-z0-9]", "a special character"),
)


def password_problems(password: str) -> list[str]:
    '''
    returns a list of problems in the password,
    or an empty list if the password is valid
    '''
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append(f"be at least {MIN_LENGTH} characters long")

    if len(password) > MAX_LENGTH:
        problems.append(f"be at most {MAX_LENGTH} characters long")

    if not re.fullmatch(ALLOWED_CHARACTERS, password):
        problems.append("use only English letters, digits and symbols, without spaces")

    problems += [
        f"contain {name}"
        for pattern, name in REQUIRED_CHARACTERS
        if not re.search(pattern, password)
    ]
    return problems


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    '''
    hashes password using PBKDF2 with SHA-512.
    '''
    problems = password_problems(password)
    if problems:
        raise ValueError("password must " + ", ".join(problems))

    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    '''
    verifies password by checking stored hash in db.
    '''
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        expected = bytes.fromhex(digest)
        derived = _derive(password, bytes.fromhex(salt), int(iterations))

    except ValueError:
        return False

    return algorithm == ALGORITHM and hmac.compare_digest(derived, expected)


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations)
