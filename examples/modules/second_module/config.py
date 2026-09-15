"""Configuration for the second_module module."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SecondModuleSettings(BaseModel):
    tenant_id:str = Field(..., description="The tenant ID for the second module.")  
