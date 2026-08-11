"""
Roblox validation — isolated module so endpoint changes are one-file fixes.
"""

import httpx


class RobloxValidationError(Exception):
    pass


async def validate_roblox_user(roblox_id: str, roblox_username: str) -> dict:
    """
    Validates that the given Roblox ID exists and that the username matches.
    Returns {"id": int, "name": str} on success.
    Raises RobloxValidationError with a user-facing message on failure.
    """
    # Reject obviously bad input (URLs, empty strings, non-numeric IDs)
    roblox_id = roblox_id.strip()
    roblox_username = roblox_username.strip()

    if not roblox_id.isdigit():
        raise RobloxValidationError(
            "Roblox ID must be a number — please paste your numeric Roblox ID, "
            "not a URL or username."
        )

    uid = int(roblox_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: resolve username -> ID to get the canonical ID for this username
        try:
            resp = await client.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [roblox_username], "excludeBannedUsers": False},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RobloxValidationError(
                f"Could not reach Roblox to verify your username. Try again shortly. ({exc})"
            )

        data = resp.json()
        results = data.get("data", [])
        if not results:
            raise RobloxValidationError(
                f"Roblox username **{roblox_username}** was not found. "
                "Check spelling and try again."
            )

        resolved_id = results[0]["id"]
        canonical_name = results[0]["name"]

        if resolved_id != uid:
            raise RobloxValidationError(
                f"The Roblox ID `{uid}` does not match username **{roblox_username}** "
                f"(that username belongs to ID `{resolved_id}`). "
                "Please provide matching ID and username."
            )

        # Step 2: fetch profile to confirm the account is accessible
        try:
            resp2 = await client.get(f"https://users.roblox.com/v1/users/{uid}")
            resp2.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise RobloxValidationError(
                    f"Roblox ID `{uid}` does not exist. Double-check your ID."
                )
            raise RobloxValidationError(
                f"Roblox returned an error while verifying your ID. Try again shortly."
            )

    return {"id": uid, "name": canonical_name}
