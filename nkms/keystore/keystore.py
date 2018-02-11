from typing import Union

from sqlalchemy.orm import sessionmaker

from nkms.crypto.constants import KFRAG_LENGTH
from nkms.crypto.signature import Signature
from nkms.crypto.utils import BytestringSplitter
from nkms.keystore.db.models import Key, PolicyContract, Workorder
from umbral.fragments import KFrag
from umbral.keys import UmbralPublicKey
from . import keypairs


class NotFound(Exception):
    """
    Exception class for KeyStore calls for objects that don't exist.
    """
    pass


class KeyStore(object):
    """
    A storage class of cryptographic keys.
    """
    kfrag_splitter = BytestringSplitter(Signature, (KFrag, KFRAG_LENGTH))

    def __init__(self, sqlalchemy_engine=None):
        """
        Initalizes a KeyStore object.

        :param sqlalchemy_engine: SQLAlchemy engine object to create session
        """
        self.session = sessionmaker(bind=sqlalchemy_engine)()

    def add_key(self,
                keypair: Union[keypairs.EncryptingKeypair,
                               keypairs.SigningKeypair]) -> Key:

        """
        :param keypair: Keypair object to store in the keystore.

        :return: The newly added key object.
        """
        fingerprint = keypair.get_fingerprint()
        key_data = keypair.serialize_pubkey(as_b64=True)
        is_signing = isinstance(keypair, keypairs.SigningKeypair)

        new_key = Key(fingerprint, key_data, is_signing)

        self.session.add(new_key)
        self.session.commit()
        return new_key


def get_key(self, fingerprint: bytes) -> Union[keypairs.EncryptingKeypair,
                                               keypairs.SigningKeypair]:
    """
    Returns a key from the KeyStore.

    :param fingerprint: Fingerprint, in bytes, of key to return

    :return: Keypair of the returned key.
    """
    key = self.session.query(Key).filter_by(fingerprint=fingerprint).first()
    if not key:
        raise NotFound(
            "No key with fingerprint {} found.".format(fingerprint))
    if key.is_signing:
        pubkey = UmbralPublicKey(key.key_data, as_b64=True)
        return keypairs.SigningKeypair(pubkey)


def del_key(self, fingerprint: bytes):
    """
    Deletes a key from the KeyStore.

    :param fingerprint: Fingerprint of key to delete
    """
    self.session.query(Key).filter_by(fingerprint=fingerprint).delete()
    self.session.commit()


def add_policy_contract(self, expiration, deposit, hrac,
                        alice_pubkey_sig, alice_pubkey_enc,
                        bob_pubkey_sig, alice_signature) -> PolicyContract:
    """
    Creates a PolicyContract to the Keystore.

    :return: The newly added PolicyContract object
    """
    # TODO: This can be optimized to one commit/write.
    alice_pubkey_sig = self.add_key(alice_pubkey_sig)
    alice_pubkey_enc = self.add_key(alice_pubkey_enc)
    bob_pubkey_sig = self.add_key(bob_pubkey_sig)

    new_policy_contract = PolicyContract(
        expiration, deposit, hrac, alice_pubkey_sig.id,
        alice_pubkey_enc.id, bob_pubkey_sig.id, alice_signature
    )

    self.session.add(new_policy_contract)

    return new_policy_contract

    def get_workorders(self, hrac: bytes) -> Workorder:
        """
        Returns a list of Workorders by HRAC.
        """
        workorders = self.session.query(Workorder).filter_by(hrac)
        if not workorders:
            raise NotFound("No Workorders with {} HRAC found.".format(hrac))
        return workorders

    def del_workorders(self, hrac: bytes):
        """
        Deletes a Workorder from the Keystore.
        """
        self.session.query(Workorder).filter_by(hrac=hrac).delete()
        self.session.commit()
