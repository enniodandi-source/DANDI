#!/usr/bin/env python3
"""
Email Consolidation Pilot - Script di automazione
Legge email da account di test e le consolida in un sistema di ticketing centrale.
"""

import json
import imaplib
import smtplib
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.parser import BytesParser
from email import policy
from datetime import datetime
import time
import hashlib

# ============================================================================
# CONFIGURAZIONE LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_consolidator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CLASSE PRINCIPALE
# ============================================================================
class EmailConsolidator:
    """
    Gestisce il consolidamento delle email dai singoli account al sistema centrale.
    """

    def __init__(self, config_file='config.json', state_file='state.json'):
        """
        Inizializza il consolidatore.

        Args:
            config_file: percorso al file di configurazione con credenziali
            state_file: percorso al file che traccia gli ID dei messaggi processati
        """
        self.config_file = Path(config_file)
        self.state_file = Path(state_file)

        # Carica configurazione
        self.config = self._load_config()

        # Carica stato (tracciamento degli ID)
        self.state = self._load_state()

    def _load_config(self) -> dict:
        """Carica il file di configurazione."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"File configurazione non trovato: {self.config_file}")

        with open(self.config_file, 'r') as f:
            config = json.load(f)

        logger.info(f"Configurazione caricata: {len(config['accounts'])} account trovati")
        return config

    def _load_state(self) -> dict:
        """Carica il file di stato. Se non esiste, ne crea uno vuoto."""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)
        else:
            logger.info("File di stato non trovato, ne creo uno nuovo")
            return {"processed_message_ids": []}

    def _save_state(self):
        """Salva il file di stato su disco."""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
        logger.debug("Stato salvato su disco")

    def _generate_message_id(self, email_data: bytes) -> str:
        """
        Genera un ID univoco per il messaggio basato sul suo contenuto.
        Questo previene l'invio duplicato dello stesso messaggio.

        Args:
            email_data: contenuto grezzo del messaggio

        Returns:
            Hash SHA256 del messaggio
        """
        return hashlib.sha256(email_data).hexdigest()

    def _is_message_processed(self, message_id: str) -> bool:
        """Verifica se il messaggio è già stato processato."""
        return message_id in self.state["processed_message_ids"]

    def _mark_message_processed(self, message_id: str):
        """Marca un messaggio come processato."""
        if message_id not in self.state["processed_message_ids"]:
            self.state["processed_message_ids"].append(message_id)

    def _fetch_emails_from_imap(self, email_account: str, password: str,
                                imap_host: str, imap_port: int = 993) -> list:
        """
        Si connette a un account IMAP e recupera i messaggi non letti/non elaborati.

        Args:
            email_account: indirizzo email
            password: password
            imap_host: host IMAP (es. imap.gmail.com)
            imap_port: porta IMAP (default 993 per SSL)

        Returns:
            Lista di tuple (email_id, raw_message_data)
        """
        messages = []

        try:
            logger.info(f"Connessione a {email_account} su {imap_host}:{imap_port}")

            # Connessione IMAP con SSL
            imap = imaplib.IMAP4_SSL(imap_host, imap_port)
            imap.login(email_account, password)

            # Seleziona la cartella INBOX
            imap.select('INBOX')

            # Cerca i messaggi (tutti per ora - puoi filtrarli per "UNSEEN" se vuoi)
            status, message_ids = imap.search(None, 'ALL')

            if status != 'OK':
                logger.warning(f"Errore nella ricerca dei messaggi per {email_account}")
                return messages

            # Se ci sono messaggi
            if message_ids[0]:
                msg_ids = message_ids[0].split()
                logger.info(f"Trovati {len(msg_ids)} messaggi in {email_account}")

                # Recupera ogni messaggio
                for msg_id in msg_ids:
                    status, msg_data = imap.fetch(msg_id, '(RFC822)')

                    if status == 'OK':
                        raw_message = msg_data[0][1]
                        message_hash = self._generate_message_id(raw_message)

                        # Se non è già stato processato, aggiungilo alla lista
                        if not self._is_message_processed(message_hash):
                            messages.append((msg_id, raw_message, message_hash))
                        else:
                            logger.debug(f"Messaggio {message_hash} già processato, saltato")

            imap.close()
            imap.logout()
            logger.info(f"Disconnessione da {email_account} completata. {len(messages)} nuovi messaggi")

        except imaplib.IMAP4.error as e:
            logger.error(f"Errore IMAP per {email_account}: {e}")
        except Exception as e:
            logger.error(f"Errore inaspettato per {email_account}: {e}")

        return messages

    def _forward_to_central_system(self, raw_message: bytes,
                                    source_email: str,
                                    central_email: str,
                                    smtp_host: str, smtp_port: int = 587,
                                    smtp_user: str = None, smtp_password: str = None) -> bool:
        """
        Invia il messaggio al sistema di ticketing centrale via SMTP.

        Args:
            raw_message: contenuto del messaggio originale
            source_email: email da cui proviene il messaggio
            central_email: email del sistema di ticketing centrale
            smtp_host: host SMTP
            smtp_port: porta SMTP (default 587 per STARTTLS)
            smtp_user: username SMTP (se None, usa central_email)
            smtp_password: password SMTP

        Returns:
            True se l'invio è riuscito, False altrimenti
        """
        try:
            # Parsa il messaggio originale
            parser = BytesParser(policy=policy.default)
            original_msg = parser.parsebytes(raw_message)

            # Crea un nuovo messaggio di inoltro
            forwarded_msg = MIMEMultipart()

            # Aggiungi header personalizzati
            forwarded_msg['From'] = smtp_user or central_email
            forwarded_msg['To'] = central_email
            forwarded_msg['Subject'] = f"[CONSOLIDATED from {source_email}] {original_msg.get('Subject', 'No Subject')}"
            forwarded_msg['X-Forwarded-From'] = source_email
            forwarded_msg['X-Consolidation-Date'] = datetime.now().isoformat()

            # Aggiungi il corpo del messaggio originale
            body = f"""
Messaggio originale inoltrato dal sistema di consolidamento.

===== DETTAGLI ORIGINALI =====
Da: {original_msg.get('From', 'Unknown')}
Oggetto: {original_msg.get('Subject', 'No Subject')}
Data: {original_msg.get('Date', 'Unknown')}

===== CONTENUTO =====
{original_msg.get_payload(decode=True).decode('utf-8', errors='replace') if original_msg.get_payload() else 'No content'}
"""

            forwarded_msg.attach(MIMEText(body, 'plain'))

            # Connessione SMTP con STARTTLS
            logger.debug(f"Connessione a {smtp_host}:{smtp_port}")
            smtp = smtplib.SMTP(smtp_host, smtp_port)
            smtp.starttls()

            # Autenticazione
            if smtp_password:
                smtp.login(smtp_user or central_email, smtp_password)

            # Invio
            smtp.send_message(forwarded_msg)
            smtp.quit()

            logger.info(f"Messaggio inoltrato da {source_email} a {central_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Errore autenticazione SMTP: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"Errore SMTP: {e}")
            return False
        except Exception as e:
            logger.error(f"Errore inaspettato durante l'invio: {e}")
            return False

    def run(self):
        """
        Esegue il ciclo principale di consolidamento.
        Per ogni account di test:
        1. Recupera i messaggi non elaborati
        2. Li invia al sistema centrale
        3. Traccia gli ID per evitare duplicati
        """
        logger.info("=" * 70)
        logger.info("INIZIO CICLO DI CONSOLIDAMENTO")
        logger.info("=" * 70)

        total_processed = 0
        total_errors = 0

        # Configurazione del sistema centrale
        central_config = self.config.get('central_system', {})
        central_email = central_config.get('email')
        smtp_host = central_config.get('smtp_host')
        smtp_port = central_config.get('smtp_port', 587)
        smtp_user = central_config.get('smtp_user')
        smtp_password = central_config.get('smtp_password')

        if not all([central_email, smtp_host]):
            logger.error("Configurazione del sistema centrale incompleta")
            return

        # Processa ogni account di test
        for account in self.config.get('accounts', []):
            email = account['email']
            password = account['password']
            imap_host = account['imap_host']
            imap_port = account.get('imap_port', 993)

            logger.info(f"\nElaborazione account: {email}")

            # Recupera i messaggi da IMAP
            messages = self._fetch_emails_from_imap(email, password, imap_host, imap_port)

            # Invia al sistema centrale
            for msg_id, raw_message, message_hash in messages:
                success = self._forward_to_central_system(
                    raw_message,
                    source_email=email,
                    central_email=central_email,
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password
                )

                if success:
                    self._mark_message_processed(message_hash)
                    total_processed += 1
                else:
                    total_errors += 1

            # Pausa tra account per evitare problemi di rate limiting
            time.sleep(1)

        # Salva lo stato
        self._save_state()

        logger.info("\n" + "=" * 70)
        logger.info(f"CICLO COMPLETATO: {total_processed} messaggi inoltrati, {total_errors} errori")
        logger.info("=" * 70)


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    try:
        consolidator = EmailConsolidator()
        consolidator.run()
    except Exception as e:
        logger.error(f"Errore critico: {e}", exc_info=True)
        exit(1)
