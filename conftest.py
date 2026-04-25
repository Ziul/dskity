"""Configuração global do pytest para todos os testes."""

from __future__ import annotations

import os

# IMPORTANTE: Define variáveis de ambiente ANTES de qualquer importação
# para evitar que módulos tentem conectar a bancos de dados reais
if not os.getenv("BIOSTATION_PERSON_DATABASE_URL"):
    os.environ["BIOSTATION_PERSON_DATABASE_URL"] = "sqlite:///:memory:"

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Configura o ambiente de teste.

    A configuração de variáveis de ambiente foi movida para o nível de módulo
    para garantir que seja executada antes de qualquer importação.
    """
    yield

    # Cleanup opcional após todos os testes
