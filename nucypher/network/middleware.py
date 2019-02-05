"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.
"""
import socket
import ssl

import requests
import time
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from twisted.logger import Logger
from umbral.cfrags import CapsuleFrag
from umbral.signing import Signature

from bytestring_splitter import BytestringSplitter, VariableLengthBytestring


class UnexpectedResponse(Exception):
    pass


class NotFound(UnexpectedResponse):
    pass


class NucypherMiddlewareClient:
    library = requests

    def parse_node_or_host_and_port(self, node, host, port):
        raise NotImplementedError()

    def invoke_method(self, method, url, *args, **kwargs):
        raise NotImplementedError()

    def __getattr__(self, method_name):
        # Quick sanity check.
        if not method_name in ("post", "get", "put", "patch", "delete"):
            raise TypeError(
                "This client is for HTTP only - you need to use a real HTTP verb, not '{}'.".format(method_name))

        def method_wrapper(path, node=None, host=None, port=None, *args, **kwargs):
            host, certificate_filepath, http_client = self.parse_node_or_host_and_port(node, host, port)
            method = getattr(http_client, method_name)

            url = "https://{}/{}".format(host, path)
            response = self.invoke_method(method, url, verify=certificate_filepath, *args, **kwargs)
            cleaned_response = self.response_cleaner(response)
            if cleaned_response.status_code >= 300:
                if cleaned_response.status_code == 404:
                    raise NotFound(
                        "While trying to {} {} ({}), server claims not to have found it.  Response: {}".format(item,
                                                                                                               args,
                                                                                                               kwargs,
                                                                                                               cleaned_response.content))
                else:
                    raise UnexpectedResponse(
                        "Unexpected response while trying to {} {},{}: {} {}".format(item, args, kwargs,
                                                                                     cleaned_response.status_code,
                                                                                     cleaned_response.content))
            return cleaned_response

        return method_wrapper

    def node_selector(self, node):
        return node.rest_url(), self.library


class RestMiddleware:
    log = Logger()

    client = NucypherMiddlewareClient()

    def get_certificate(self, host, port, timeout=3, retry_attempts: int = 3, retry_rate: int = 2,
                        current_attempt: int = 0):

        socket.setdefaulttimeout(timeout)  # Set Socket Timeout

        try:
            self.log.info("Fetching seednode {}:{} TLS certificate".format(host, port))
            seednode_certificate = ssl.get_server_certificate(addr=(host, port))

        except socket.timeout:
            if current_attempt == retry_attempts:
                message = "No Response from seednode {}:{} after {} attempts"
                self.log.info(message.format(host, port, retry_attempts))
                raise RuntimeError("No response from {}:{}".format(host, port))
            self.log.info("No Response from seednode {}. Retrying in {} seconds...".format(host, retry_rate))
            time.sleep(retry_rate)
            return self.get_certificate(host, port, timeout, retry_attempts, retry_rate, current_attempt + 1)

        else:
            certificate = x509.load_pem_x509_certificate(seednode_certificate.encode(),
                                                         backend=default_backend())
            return certificate

    def consider_arrangement(self, arrangement):
        node = arrangement.ursula
        response = self.client.post(node=node,
                                    path="consider_arrangement",
                                    data=bytes(arrangement),
                                    timeout=2,
                                    )
        return response

    def enact_policy(self, ursula, id, payload):
        response = self.client.post(node=ursula,
                                    path='kFrag/{}'.format(id.hex()),
                                    data=payload,
                                    timeout=2)
        return True, ursula.stamp.as_umbral_pubkey()

    def reencrypt(self, work_order):
        ursula_rest_response = self.send_work_order_payload_to_ursula(work_order)
        # TODO: Check status code.
        splitter = BytestringSplitter((CapsuleFrag, VariableLengthBytestring), Signature)
        cfrags_and_signatures = splitter.repeat(ursula_rest_response.content)
        cfrags = work_order.complete(cfrags_and_signatures)
        return cfrags

    def revoke_arrangement(self, ursula, revocation):
        # TODO: Implement revocation confirmations
        response = self.client.delete("https://{}/kFrag/{}".format(ursula.rest_interface,
                                                                   revocation.arrangement_id.hex()),
                                      bytes(revocation),
                                      )
        return response

    def get_competitive_rate(self):
        return NotImplemented

    def get_treasure_map_from_node(self, node, map_id):
        endpoint = "https://{}/treasure_map/{}".format(node.rest_interface, map_id)
        response = self.client.get(endpoint, timeout=2)
        return response

    def put_treasure_map_on_node(self, node, map_id, map_payload):
        response = self.client.post(node=node,
                                    path="treasure_map/{}".format(map_id),
                                    data=map_payload,
                                    timeout=2)
        return response

    def send_work_order_payload_to_ursula(self, work_order):
        payload = work_order.payload()
        id_as_hex = work_order.arrangement_id.hex()
        endpoint = 'https://{}/kFrag/{}/reencrypt'.format(work_order.ursula.rest_interface, id_as_hex)
        return self.client.post(endpoint, payload, timeout=2)

    def node_information(self, host, port, certificate_filepath):
        response = self.client.get(host=host, port=port,
                                   path="public_information",
                                   timeout=2)
        return response.content

    def get_nodes_via_rest(self,
                           url,
                           certificate_filepath,
                           announce_nodes=None,
                           nodes_i_need=None,
                           client=requests,
                           fleet_checksum=None):
        if nodes_i_need:
            # TODO: This needs to actually do something.
            # Include node_ids in the request; if the teacher node doesn't know about the
            # nodes matching these ids, then it will ask other nodes.
            pass

        if fleet_checksum:
            params = {'fleet': fleet_checksum}
        else:
            params = {}

        req_kwargs = {}

        if client is requests:
            req_kwargs["verify"] = certificate_filepath
            req_kwargs["timeout"] = 2
            req_kwargs["params"] = params
        else:
            req_kwargs["query_string"] = params

        if announce_nodes:
            payload = bytes().join(bytes(VariableLengthBytestring(n)) for n in announce_nodes)
            response = client.post("https://{}/node_metadata".format(url),
                                   data=payload,
                                   **req_kwargs)
        else:
            response = client.get("https://{}/node_metadata".format(url), **req_kwargs)

        return response
