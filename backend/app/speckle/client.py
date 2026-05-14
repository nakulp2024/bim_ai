from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from ..config import settings


class SpeckleClient:
    """Thin GraphQL passthrough using the user's Speckle access token.

    Uses settings.speckle_internal_url for server-to-server calls.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self.endpoint = f"{settings.speckle_internal_url}/graphql"

    async def gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                self.endpoint,
                headers={"authorization": f"Bearer {self.token}"},
                json={"query": query, "variables": variables or {}},
            )
        if resp.status_code != 200:
            raise HTTPException(502, detail=f"speckle gql {resp.status_code}: {resp.text}")
        data = resp.json()
        if "errors" in data:
            raise HTTPException(502, detail=f"speckle gql errors: {data['errors']}")
        return data["data"]

    async def active_user(self) -> dict[str, Any]:
        data = await self.gql(
            "query { activeUser { id name email avatar } }"
        )
        if not data.get("activeUser"):
            raise HTTPException(401, detail="no active speckle user for token")
        return data["activeUser"]

    async def projects(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self.gql(
            """
            query MyProjects($limit: Int!) {
              activeUser {
                projects(limit: $limit) {
                  items { id name description updatedAt role }
                }
              }
            }
            """,
            {"limit": limit},
        )
        return data["activeUser"]["projects"]["items"]

    async def models(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self.gql(
            """
            query ProjectModels($id: String!, $limit: Int!) {
              project(id: $id) {
                id
                name
                models(limit: $limit) {
                  items { id name updatedAt }
                }
              }
            }
            """,
            {"id": project_id, "limit": limit},
        )
        return data["project"]["models"]["items"]

    async def versions(
        self, project_id: str, model_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        data = await self.gql(
            """
            query ModelVersions($pid: String!, $mid: String!, $limit: Int!) {
              project(id: $pid) {
                model(id: $mid) {
                  versions(limit: $limit) {
                    items {
                      id
                      referencedObject
                      message
                      sourceApplication
                      createdAt
                    }
                  }
                }
              }
            }
            """,
            {"pid": project_id, "mid": model_id, "limit": limit},
        )
        return data["project"]["model"]["versions"]["items"]
