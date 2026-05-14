from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import User, get_session
from ..speckle.client import SpeckleClient
from .jwt_tokens import issue_jwt

router = APIRouter(prefix="/auth/speckle", tags=["auth"])

_CHALLENGE_COOKIE = "speckle_challenge"
_signer = URLSafeSerializer(settings.session_secret, salt="speckle-oauth")


@router.get("/start")
def start() -> Response:
    if not settings.speckle_app_id:
        raise HTTPException(500, detail="SPECKLE_APP_ID not configured")
    challenge = secrets.token_urlsafe(32)
    redirect_url = (
        f"{settings.speckle_public_url}/authn/verify/"
        f"{settings.speckle_app_id}/{challenge}"
    )
    resp = RedirectResponse(redirect_url)
    resp.set_cookie(
        _CHALLENGE_COOKIE,
        _signer.dumps(challenge),
        httponly=True,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return resp


@router.get("/callback")
async def callback(
    request: Request,
    access_code: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if not access_code:
        raise HTTPException(400, detail="missing access_code")

    signed = request.cookies.get(_CHALLENGE_COOKIE)
    if not signed:
        raise HTTPException(400, detail="missing challenge cookie")
    try:
        challenge = _signer.loads(signed)
    except BadSignature as e:
        raise HTTPException(400, detail="bad challenge cookie") from e

    async with httpx.AsyncClient(timeout=15) as http:
        tok_resp = await http.post(
            f"{settings.speckle_internal_url}/auth/token",
            json={
                "accessCode": access_code,
                "appId": settings.speckle_app_id,
                "appSecret": settings.speckle_app_secret,
                "challenge": challenge,
            },
        )
        if tok_resp.status_code != 200:
            raise HTTPException(401, detail=f"speckle token exchange failed: {tok_resp.text}")
        tok = tok_resp.json()

    access_token: str = tok["token"]
    refresh_token: str | None = tok.get("refreshToken")
    expires_in: int | None = tok.get("tokenExpiresIn")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in
        else None
    )

    me = await SpeckleClient(access_token).active_user()
    speckle_user_id = me["id"]

    result = await session.execute(
        select(User).where(User.speckle_user_id == speckle_user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid.uuid4().hex,
            speckle_user_id=speckle_user_id,
            name=me.get("name"),
            email=me.get("email"),
            avatar=me.get("avatar"),
            speckle_access_token=access_token,
            speckle_refresh_token=refresh_token,
            speckle_token_expires_at=expires_at,
        )
        session.add(user)
    else:
        user.speckle_access_token = access_token
        user.speckle_refresh_token = refresh_token
        user.speckle_token_expires_at = expires_at
        user.name = me.get("name") or user.name
        user.email = me.get("email") or user.email
        user.avatar = me.get("avatar") or user.avatar
    await session.commit()

    jwt_token = issue_jwt(user.id)
    redirect = RedirectResponse(f"{settings.app_base_url}/auth/callback#token={jwt_token}")
    redirect.delete_cookie(_CHALLENGE_COOKIE, path="/")
    return redirect
