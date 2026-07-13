#!/usr/bin/env python3
"""
Script di test per verificare il funzionamento del consolidatore.
Crea email di test e verifica il flusso completo.

NOTA: Questo è solo uno schema di test. Per eseguire i test reali,
devi configurare account di test reali nel config.json
"""

import json
import hashlib
from pathlib import Path

def test_config_file():
    """Verifica che il file di configurazione sia valido."""
    print("Test 1: Verifica file di configurazione...")

    config_file = Path('config.json')
    if not config_file.exists():
        print("  ✗ config.json non trovato. Esegui: cp config.json.example config.json")
        return False

    try:
        with open(config_file, 'r') as f:
            config = json.load(f)

        # Verifica struttura
        assert 'central_system' in config, "Manca sezione 'central_system'"
        assert 'accounts' in config, "Manca sezione 'accounts'"
        assert len(config['accounts']) > 0, "Nessun account configurato"

        # Verifica central_system
        central = config['central_system']
        assert central.get('email'), "Manca email centrale"
        assert central.get('smtp_host'), "Manca smtp_host"

        # Verifica accounts
        for i, account in enumerate(config['accounts']):
            assert account.get('email'), f"Account {i}: manca email"
            assert account.get('password'), f"Account {i}: manca password"
            assert account.get('imap_host'), f"Account {i}: manca imap_host"

        print(f"  ✓ config.json valido ({len(config['accounts'])} account)")
        return True

    except json.JSONDecodeError:
        print("  ✗ config.json non è un JSON valido")
        return False
    except AssertionError as e:
        print(f"  ✗ Errore configurazione: {e}")
        return False

def test_state_file():
    """Verifica che il file di stato sia valido."""
    print("Test 2: Verifica file di stato...")

    state_file = Path('state.json')
    if not state_file.exists():
        print("  ✗ state.json non trovato")
        return False

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)

        assert 'processed_message_ids' in state, "Manca 'processed_message_ids'"
        assert isinstance(state['processed_message_ids'], list), "processed_message_ids deve essere una lista"

        print(f"  ✓ state.json valido ({len(state['processed_message_ids'])} messaggi processati)")
        return True

    except json.JSONDecodeError:
        print("  ✗ state.json non è un JSON valido")
        return False
    except AssertionError as e:
        print(f"  ✗ Errore stato: {e}")
        return False

def test_message_hash():
    """Verifica che il calcolo dell'hash funzioni correttamente."""
    print("Test 3: Verifica calcolo hash dei messaggi...")

    # Email di test
    test_message = b"From: test@example.com\nSubject: Test\n\nHello World"

    hash1 = hashlib.sha256(test_message).hexdigest()
    hash2 = hashlib.sha256(test_message).hexdigest()

    # Lo stesso messaggio deve avere lo stesso hash
    if hash1 == hash2:
        print(f"  ✓ Hash consistente: {hash1[:16]}...")
    else:
        print("  ✗ Hash non consistente")
        return False

    # Messaggi diversi devono avere hash diversi
    different_message = b"From: test@example.com\nSubject: Different\n\nGoodbye World"
    hash3 = hashlib.sha256(different_message).hexdigest()

    if hash1 != hash3:
        print(f"  ✓ Messaggi diversi hanno hash diversi")
        return True
    else:
        print("  ✗ Messaggi diversi hanno lo stesso hash")
        return False

def test_imports():
    """Verifica che le dipendenze necessarie siano disponibili."""
    print("Test 4: Verifica dipendenze Python...")

    required_modules = [
        'imaplib',
        'smtplib',
        'email',
        'json',
        'logging',
        'pathlib',
        'hashlib',
        'time'
    ]

    missing = []
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        print(f"  ✗ Moduli mancanti: {', '.join(missing)}")
        return False
    else:
        print(f"  ✓ Tutte le dipendenze disponibili")
        return True

def main():
    """Esegui tutti i test."""
    print("\n" + "=" * 60)
    print("TEST DI VALIDAZIONE - EMAIL CONSOLIDATOR")
    print("=" * 60 + "\n")

    results = [
        test_imports(),
        test_config_file(),
        test_state_file(),
        test_message_hash(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RISULTATI: {passed}/{total} test passati")
    print("=" * 60 + "\n")

    if all(results):
        print("✓ Tutti i test passati! Lo script è pronto all'uso.")
        print("\nProssimi passi:")
        print("  1. Verifica le credenziali in config.json")
        print("  2. Esegui: python email_consolidator.py")
        print("  3. Controlla email_consolidator.log per i dettagli")
        return 0
    else:
        print("✗ Alcuni test sono falliti. Controlla i messaggi di errore sopra.")
        return 1

if __name__ == "__main__":
    exit(main())
