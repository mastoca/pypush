import plistlib
from base64 import b64decode

import requests

from ._helpers import PROTOCOL_VERSION, KeyPair, parse_key, serialize_key
from .signing import add_auth_signature, armour_cert

from io import BytesIO

from cryptography.hazmat.primitives.asymmetric import ec, rsa

from typing import Self

import logging

logger = logging.getLogger("ids")


class IDSIdentity:
    def __init__(
        self,
        signing_key: str | None = None,
        encryption_key: str | None = None,
        signing_public_key: str | None = None,
        encryption_public_key: str | None = None,
    ):
        if signing_key is not None:
            self.signing_key = signing_key
            self.signing_public_key = serialize_key(parse_key(signing_key).public_key())  # type: ignore
        elif signing_public_key is not None:
            self.signing_key = None
            self.signing_public_key = signing_public_key
        else:
            # Generate a new key
            self.signing_key = serialize_key(ec.generate_private_key(ec.SECP256R1()))
            self.signing_public_key = serialize_key(parse_key(self.signing_key).public_key())  # type: ignore

        if encryption_key is not None:
            self.encryption_key = encryption_key
            self.encryption_public_key = serialize_key(parse_key(encryption_key).public_key())  # type: ignore
        elif encryption_public_key is not None:
            self.encryption_key = None
            self.encryption_public_key = encryption_public_key
        else:
            self.encryption_key = serialize_key(rsa.generate_private_key(65537, 1280))
            self.encryption_public_key = serialize_key(parse_key(self.encryption_key).public_key())  # type: ignore

    @classmethod
    def decode(cls, inp: bytes) -> Self:
        input = BytesIO(inp)

        assert input.read(5) == b"\x30\x81\xF6\x81\x43"  # DER header
        raw_ecdsa = input.read(67)
        assert input.read(3) == b"\x82\x81\xAE"  # DER header
        raw_rsa = input.read(174)

        # Parse the RSA key
        raw_rsa = BytesIO(raw_rsa)
        assert raw_rsa.read(2) == b"\x00\xAC"  # Not sure what this is
        assert raw_rsa.read(3) == b"\x30\x81\xA9"  # Inner DER header
        assert raw_rsa.read(3) == b"\x02\x81\xA1"
        rsa_modulus = raw_rsa.read(161)
        rsa_modulus = int.from_bytes(rsa_modulus, "big")
        assert (
            raw_rsa.read(5) == b"\x02\x03\x01\x00\x01"
        )  # Exponent, should always be 65537

        # Parse the EC key
        assert raw_ecdsa[:3] == b"\x00\x41\x04"
        raw_ecdsa = raw_ecdsa[3:]
        ec_x = int.from_bytes(raw_ecdsa[:32], "big")
        ec_y = int.from_bytes(raw_ecdsa[32:], "big")

        ec_key = ec.EllipticCurvePublicNumbers(ec_x, ec_y, ec.SECP256R1())
        ec_key = ec_key.public_key()

        rsa_key = rsa.RSAPublicNumbers(e=65537, n=rsa_modulus)
        rsa_key = rsa_key.public_key()

        return IDSIdentity(
            signing_public_key=serialize_key(ec_key),
            encryption_public_key=serialize_key(rsa_key),
        )

    def encode(self) -> bytes:
        output = BytesIO()

        raw_rsa = BytesIO()
        raw_rsa.write(b"\x00\xAC")
        raw_rsa.write(b"\x30\x81\xA9")
        raw_rsa.write(b"\x02\x81\xA1")
        raw_rsa.write(parse_key(self.encryption_public_key).public_numbers().n.to_bytes(161, "big"))  # type: ignore
        raw_rsa.write(b"\x02\x03\x01\x00\x01")  # Hardcode the exponent

        output.write(b"\x30\x81\xF6\x81\x43")
        output.write(b"\x00\x41\x04")
        output.write(parse_key(self.signing_public_key).public_numbers().x.to_bytes(32, "big"))  # type: ignore
        output.write(parse_key(self.signing_public_key).public_numbers().y.to_bytes(32, "big"))  # type: ignore

        output.write(b"\x82\x81\xAE")
        output.write(raw_rsa.getvalue())

        return output.getvalue()


def register(
    push_token,
    handles,
    user_id,
    auth_key: KeyPair,
    push_key: KeyPair,
    identity: IDSIdentity,
    validation_data,
):
    logger.debug(f"Registering IDS identity for {handles}")
    uris = [{"uri": handle} for handle in handles]
    import uuid

    body = {
        "device-name": "pypush",
        "hardware-version": "MacBookPro18,3",
        "language": "en-US",
        "os-version": "macOS,13.2.1,22D68",
        "software-version": "22D68",
        "private-device-data": {
            "u": uuid.uuid4().hex.upper(),
        },
        "services": [
            {
                "capabilities": [{"flags": 1, "name": "Messenger", "version": 1}],
                "service": "com.apple.madrid",
                "sub-services": [
                    "com.apple.private.alloy.sms",
                    "com.apple.private.alloy.gelato",
                    "com.apple.private.alloy.biz",
                    "com.apple.private.alloy.gamecenter.imessage",
                ],
                "users": [
                    {
                        "client-data": {
                            "is-c2k-equipment": True,
                            "optionally-receive-typing-indicators": True,
                            "public-message-identity-key": identity.encode(),
                            "public-message-identity-version": 2,
                            "show-peer-errors": True,
                            "supports-ack-v1": True,
                            "supports-activity-sharing-v1": True,
                            "supports-audio-messaging-v2": True,
                            "supports-autoloopvideo-v1": True,
                            "supports-be-v1": True,
                            "supports-ca-v1": True,
                            "supports-fsm-v1": True,
                            "supports-fsm-v2": True,
                            "supports-fsm-v3": True,
                            "supports-ii-v1": True,
                            "supports-impact-v1": True,
                            "supports-inline-attachments": True,
                            "supports-keep-receipts": True,
                            "supports-location-sharing": True,
                            "supports-media-v2": True,
                            "supports-photos-extension-v1": True,
                            "supports-st-v1": True,
                            "supports-update-attachments-v1": True,
                        },
                        "uris": uris,
                        "user-id": user_id,
                    }
                ],
            },
            {
                "capabilities": [{"flags": 1, "name": "Invitation", "version": 1}],
                "service": "com.apple.private.alloy.facetime.multi",
                "sub-services": [],
                "users": [
                    {
                        # "client-data": {
                        #     "public-message-identity-key": identity.encode(),
                        #     "public-message-identity-version": 2,
                        #     "supports-avless": True,
                        #     "supports-co": True,
                        #     "supports-gft-calls": True,
                        #     "supports-gft-errors": True,
                        #     "supports-modern-gft": True,
                        #     "supports-self-one-to-one-invites": True,
                        # },
                        "client-data": {
                    "public-message-ngm-device-prekey-data-key": b"\n \xb4\\\x15\x8e\xa4\xc8\xe5\x07\x98\tp\xd0\xa4^\x84k\x05#Ep\xa9*\xcd\xadt\xf5\xb0\xfb\xa6_ho\x12@\xe3\xf5\xcaOwh\xfd\xb9\xecD\t\x0e\x9e\xb8\xb0\xa1\x1c=\x92\x9dD/lmL\xde.\\o\xeb\x15>\x9f\xae\xd9\xf9\xd1\x9c*\x8dU\xe0\xd2\xdeo\xb2\xcb\xd8\xf8i\xd4\xd0a^\t!\x0fa\xb2\xddI\xfc_*\x19\xb2\xf0#\x12\xe0@\xd9A",
                    "supports-avless": True,
                    "public-message-identity-key": b"0\x81\xf6\x81C\x00A\x04\x87\x1e\xeb\xe4u\x0b\xa3\x9e\x9c\xbc\xf8rK\x1e\xfe44%f$\x1d\xe8\xbb\xc6\xbdCD\x9ckv K\xc1\x1e\xb1\xdf4\xc8S6\x0f\x92\xd0=\x1e\x84\x9c\xc5\xa5\xb6\xb7}\xdd\xec\x1e\x1e\xd8Q\xd8\xca\xdb\x07'\xc7\x82\x81\xae\x00\xac0\x81\xa9\x02\x81\xa1\x00\xa8 \xfc\x9f\xa6\xb0V2\xce\x1c\xa7\x13\x9e\x03\xd1\xd8\x97a\xbb\xdd\xac\x86\xb8\x10(\x89\x13QP\x8f\xf0+EP\xd1\xb06\xee\x94\xcd\xa8\x9e\xf1\xedp\xa4\x9726\x1e\xe9\xab\xd4\xcb\xac\x05\xd7\x8c?\xbb\xa2\xde,\xfe\r\x1a\xb9\x88W@\x99\xec\xa0]\r\x1a>dV\xb2@\xc5P\xf3m\x80y\xf5\xa0G\xae\xd8h\x92\xef\xca\x85\xcbB\xed\xa9W\x8c\x13\xd4O\xdbYI2\xdcM\x1f\xf6c\x17\x1c\xd1v\xdd\xbcc\xac,&V\xfd\x07\xa0\xc3\x9f\x00\x1f\xc6\xe4\x02u\x12p\x8f\xe2\xb0\x14\xfai\x12\xbb\xa6\x9a6Q\xa5\xde+\x9e{\xcf\xc8\x1b}\x02\x03\x01\x00\x01",
                    "supports-gft-calls": True,
                    "public-message-identity-version": 2.0,
                    "supports-co": True,
                    "supports-gft-errors": True,
                    "supports-self-one-to-one-invites": True,
                    "supports-modern-gft": True,
                    "public-message-identity-ngm-version": 12.0,
                    "device-key-signature": b"0a\x04\x14\x1d\xb02~\xefk&\xf8\r;R\xa4\x95c~\x8a\x90H\x85\xb0\x02\x01\x01\x04F0D\x02 @\xce\xa7P6\x89\x92Wf\x87\xc9\xc5M-\xb1\xe5Q\x9f\x7fKi\x1bp\xd5\x12\x1c,:\xdb\xed\x08\x12\x02 l\xfd\\\xe2\xd3:,\xc1\xd8\x08|\xbe\x05M\x12\xee@\xc2=eR8:\xa7h3u|\x83ia\x19",
                },
                    "kt-loggable-data": b'\n"\n \rl\xbe\xca\xf7\xe8\xb2\x89k\x18\x1e\xb9,d\xf8\xe2\n\xbf\x8d\xe1E\xd6\xf3T\xcb\xd9\x99d\xd1mk\xeb\x10\x0c\x18\x05',

                        "uris": uris,
                        "user-id": user_id,
                    }
                ],
            },
            {
                "capabilities": [{"flags": 1, "name": "Invitation", "version": 21}],
                "service": "com.apple.ess",
                "sub-services": [
                    "com.apple.private.alloy.facetime.video",
                    "com.apple.private.alloy.facetime.sync",
                    "com.apple.private.alloy.facetime.lp",
                    "com.apple.private.alloy.facetime.mw",
                ],
                "users": [
                    {
                        "client-data": {
                            "public-message-identity-key": identity.encode(),
                            "public-message-identity-version": 2,
                            "supports-avless": True,
                            "supports-co": True,
                            "supports-gft-calls": True,
                            "supports-gft-errors": True,
                            "supports-modern-gft": True,
                            "supports-self-one-to-one-invites": True,
                        },
                        "uris": uris,
                        "user-id": user_id,
                    }
                ],
            },
            {
                "capabilities": [
                    {"flags": 1, "name": "com.apple.private.alloy", "version": 1}
                ],
                "service": "com.apple.private.alloy.multiplex1",
                "sub-services": [
                    "com.apple.private.alloy.continuity.encryption",
                    "com.apple.private.alloy.willow.stream",
                    "com.apple.private.alloy.status.keysharing",
                    "com.apple.private.alloy.ids.cloudmessaging",
                    "com.apple.private.alloy.avconference.icloud",
                    "com.apple.private.alloy.keytransparency.accountkey.pinning",
                    "com.apple.private.alloy.gamecenter",
                    "com.apple.private.alloy.thumper.keys",
                    "com.apple.private.alloy.electrictouch",
                    "com.apple.private.alloy.alarms-timers",
                    "com.apple.private.alloy.continuity.activity",
                    "com.apple.private.alloy.home.invite",
                    "com.apple.private.alloy.safeview",
                    "com.apple.private.alloy.screensharing.qr",
                    "com.apple.private.alloy.phone.auth",
                    "com.apple.private.alloy.home",
                    "com.apple.private.alloy.groupkit.invite",
                    "com.apple.private.alloy.fmf",
                    "com.apple.private.alloy.continuity.tethering",
                    "com.apple.private.alloy.status.personal",
                    "com.apple.private.alloy.amp.potluck",
                    "com.apple.private.alloy.screentime",
                    "com.apple.private.alloy.copresence",
                    "com.apple.private.alloy.screentime.invite",
                    "com.apple.private.alloy.tips",
                    "com.apple.private.alloy.siri.icloud",
                    "com.apple.private.alloy.maps.eta",
                    "com.apple.private.alloy.phonecontinuity",
                    "com.apple.private.alloy.sleep.icloud",
                    "com.apple.private.alloy.usagetracking",
                    "com.apple.private.alloy.icloudpairing",
                    "com.apple.private.alloy.clockface.sharing",
                    "com.apple.private.alloy.carmelsync",
                    "com.apple.private.alloy.messagenotification",
                    "com.apple.private.alloy.digitalhealth",
                    "com.apple.private.alloy.ded",
                    "com.apple.private.alloy.screensharing",
                    "com.apple.private.alloy.contextsync",
                    "com.apple.private.alloy.accessibility.switchcontrol",
                    "com.apple.private.alloy.familycontrols",
                    "com.apple.private.alloy.fmd",
                    "com.apple.private.alloy.willow",
                    "com.apple.private.alloy.coreduet.sync",
                    "com.apple.private.alloy.nearby",
                    "com.apple.private.alloy.safari.groupactivities",
                    "com.apple.private.alloy.groupkit",
                    "com.apple.private.alloy.accounts.representative",
                    "com.apple.private.alloy.notes",
                    "com.apple.private.alloy.classroom",
                    "com.apple.private.alloy.applepay",
                    "com.apple.private.alloy.proxiedcrashcopier.icloud",
                    "com.apple.private.alloy.continuity.unlock",
                    "com.apple.private.alloy.nearby.family",
                ],
                "users": [
                    {
                        "client-data": {
                            "public-message-identity-key": identity.encode(),
                            "public-message-identity-version": 2,
                            "supports-beacon-sharing-v2": True,
                            "supports-beneficiary-invites": True,
                            "supports-cross-platform-sharing": True,
                            "supports-fmd-v2": True,
                            "supports-incoming-fmd-v1": True,
                            "supports-maps-routing-path-leg": True,
                            "supports-maps-waypoint-route-sharing": True,
                            "supports-screen-time-v2": True,
                            "supports-secure-loc-v1": True,
                        },
                        "uris": uris,
                        "user-id": user_id,
                    }
                ],
            },
        ],
        "validation-data": b64decode(validation_data),
    }

    body = plistlib.dumps(body)

    headers = {
        "x-protocol-version": PROTOCOL_VERSION,
        "x-auth-user-id-0": user_id,
    }
    add_auth_signature(headers, body, "id-register", auth_key, push_key, push_token, 0)

    r = requests.post(
        "https://identity.ess.apple.com/WebObjects/TDIdentityService.woa/wa/register",
        headers=headers,
        data=body,
        verify=False,
    )
    r = plistlib.loads(r.content)
    # print(f'Response code: {r["status"]}')
    logger.debug(f"Recieved response to IDS registration: {r}")
    if "status" in r and r["status"] == 6004:
        raise Exception("Validation data expired!")
    # TODO: Do validation of nested statuses
    if "status" in r and r["status"] != 0:
        raise Exception(f"Failed to register: {r}")
    if not "services" in r:
        raise Exception(f"No services in response: {r}")
    if not "users" in r["services"][0]:
        raise Exception(f"No users in response: {r}")
    if not "cert" in r["services"][0]["users"][0]:
        raise Exception(f"No cert in response: {r}")

    return {
        "com.apple.madrid": armour_cert(r["services"][0]["users"][0]["cert"]),
        "com.apple.private.alloy.facetime.multi": armour_cert(
            r["services"][1]["users"][0]["cert"]
        ),
        "com.apple.ess": armour_cert(r["services"][2]["users"][0]["cert"]),
        "com.apple.private.alloy.multiplex1": armour_cert(r["services"][3]["users"][0]["cert"]),

    }

    # return armour_cert(r["services"][0]["users"][0]["cert"])
