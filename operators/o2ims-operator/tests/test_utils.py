###########################################################################
# Copyright 2025 The Nephio Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##########################################################################

import http.server
import os
import random
import string
import threading

import certifi
import pytest
import responses

from controllers import utils
from controllers.utils import (
    KUBERNETES_BASE_URL,
    create_package_variant,
    get_package_variant,
    check_o2ims_provisioning_request,
    get_capi_cluster,
    )

# Constants used for testing
NAME = "test_name"
NAMESPACE = "test_ns"
TEST_JSON = {"status": {"conditions": [{"message": "test"}]}, "message": "message"}
PV_PARAM = {
    "name": "name",
    "repo_location": "location",
    "template_name": "template",
    "template_version": "version",
    "cluster_name": "cluster",
    "mutators": "mutators",
    "namespace": "namespace",
    "create": False,
}
PV_REV = {
    "items": [
        {
            "metadata": {"name": "name"},
            "spec": {"lifecycle": "lifecycle", "packageName": NAME},
        }
    ]
}
PR_PARAMS = {
    "status": {
        "provisioningStatus": "provisioningStatus",
        "provisionedResourceSet": "provisionedResourceSet",
    }
}
PACKAGE_VARIANTS_URI = f"{KUBERNETES_BASE_URL}/apis/config.porch.kpt.dev/v1alpha1/namespaces/{NAMESPACE}/packagevariants"
PACKAGE_REVISIONS_URI = f"{KUBERNETES_BASE_URL}/apis/porch.kpt.dev/v1alpha1/namespaces/{NAMESPACE}/packagerevisions"
PROVISIONING_REQUEST_URI = f"{KUBERNETES_BASE_URL}/apis/o2ims.provisioning.oran.org/v1alpha1/provisioningrequests"
CAPI_URI = f"{KUBERNETES_BASE_URL}/apis/cluster.x-k8s.io/v1beta1/namespaces/{NAMESPACE}/clusters/{NAME}"


@pytest.fixture(autouse=True)
def setup_and_teardown():
    # Create a test token in /tmp
    test_utils_token_path = "/tmp/test_utils_token"
    test_utils_token_path += "".join(random.choices(string.ascii_letters + string.digits, k=10))
    os.environ["TOKEN"] = test_utils_token_path
    with open(test_utils_token_path, "w") as fp:
        pass
    # Wait for tests to finish
    yield
    # Cleanup token
    if os.path.exists(test_utils_token_path):
        os.remove(test_utils_token_path)


@responses.activate
@pytest.mark.parametrize(
    "get_code, post_code, status, create, response_2, response_2_value, exception",
    [
        (200, None, True, False, "name", NAME, False),
        (401, None, False, False, "reason", "unauthorized", False),
        (403, None, False, False, "reason", "unauthorized", False),
        (404, 200, True, True, "name", NAME, False),
        (404, 201, True, True, "name", NAME, False),
        (404, 401, False, True, "reason", "unauthorized", False),
        (404, 403, False, True, "reason", "unauthorized", False),
        (404, 404, False, True, "reason", "notFound", False),
        (404, 400, False, True, "reason", TEST_JSON["message"], False),
        (404, 1234, False, True, "reason", TEST_JSON, False),
        (404, None, False, True, "reason", "NotAbleToCommunicateWithTheCluster ", True),
        (404, 200, False, False, "reason", "notFound", False),
        (500, None, False, False, "reason", "k8sApi server is not reachable", False),
        (1234, None, False, False, "reason", TEST_JSON, False),
        (None, None, False, False, "reason", "NotAbleToCommunicateWithTheCluster ", True),
    ],
)
def test_create_package_variant(get_code, post_code, status, create, response_2, response_2_value, exception):
    if not exception:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            json=TEST_JSON,
            status=get_code,
        )
    else:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            body=Exception(""),
        )

    pv_params = PV_PARAM.copy()
    if get_code == 404 and create:
        responses.post(
            PACKAGE_VARIANTS_URI,
            json=TEST_JSON,
            status=post_code,
        )
        pv_params.update({"create": True})

    response = create_package_variant(NAME, NAMESPACE, pv_params)
    assert response["status"] == status and response[response_2] == response_2_value


@responses.activate
@pytest.mark.parametrize(
    "http_code, status, response_2, response_2_value, response_3, response_3_value, exception",
    [
        (200, True, "name", NAME, "body", TEST_JSON, False),
        (401, False, "reason", "unauthorized", None, None, False),
        (403, False, "reason", "unauthorized", None, None, False),
        (404, False, "reason", "notFound", None, None, False),
        (1234, False, "reason", TEST_JSON, None, None, False),
        (None, False, "reason", "NotAbleToCommunicateWithTheCluster ", None, None, True),
    ],
)
def test_get_package_variant(
    http_code,
    status,
    response_2,
    response_2_value,
    response_3,
    response_3_value,
    exception,
):
    if not exception:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            json=TEST_JSON,
            status=http_code,
        )
    else:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            body=Exception(""),
        )
    response = get_package_variant(NAME, NAMESPACE)
    assert response["status"] == status and response[response_2] == response_2_value
    if response_3:
        assert response[response_3] == response_3_value


@responses.activate
@pytest.mark.parametrize(
    "pr_code, status, status_response, pv_code, response_2, response_2_value, response_3, response_3_value, response_3_exception, exception",
    [
        (200, True, True, None, "provisioningStatus", PR_PARAMS["status"]["provisioningStatus"], None, None, None, False),
        (
            200,
            True,
            False,
            None,
            "provisioningStatus",
            {
                "provisioningMessage": "Cluster provisioning request received",
                "provisioningState": "progressing",
            },
            None,
            None,
            None,
            False,
        ),
        (401, False, False, None, "reason", "unauthorized", None, None, None, False),
        (403, False, False, None, "reason", "unauthorized", None, None, None, False),
        (404, False, False, 200, "reason", "notFound", "pv", True, None, False),
        (404, False, False, 401, "reason", "notFound", "pv", False, None, False),
        (404, False, False, 403, "reason", "notFound", "pv", False, None, False),
        (404, False, False, 404, "reason", "notFound", "pv", False, None, False),
        (404, False, False, 1234, "reason", "notFound", "pv", False, None, False),
        (404, False, False, None, "reason", "notFound", "pv", False, True, False),
        (1234, False, False, None, "reason", PR_PARAMS, None, None, None, False),
        (None, False, False, None, "reason", "NotAbleToCommunicateWithTheCluster ", None, None, None, True),
    ],
)
def test_check_o2ims_provisioning_request(
    pr_code,
    status,
    status_response,
    pv_code,
    response_2,
    response_2_value,
    response_3,
    response_3_value,
    response_3_exception,
    exception,
):
    if not exception:
        pr_params = PR_PARAMS.copy()
        if pr_code == 200 and not status_response:
            pr_params.pop("status")

        responses.get(
            PROVISIONING_REQUEST_URI,
            json=pr_params,
            status=pr_code,
        )

    else:
        responses.get(
            PROVISIONING_REQUEST_URI,
            body=Exception(""),
        )

    if pv_code and not response_3_exception:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            json=TEST_JSON,
            status=pv_code,
        )
    elif pv_code and response_3_exception:
        responses.get(
            f"{PACKAGE_VARIANTS_URI}/{NAME}",
            body=Exception(""),
        )
    response = check_o2ims_provisioning_request(NAME, NAMESPACE)
    print(response)
    assert response["status"] == status and response[response_2] == response_2_value

    if pv_code:
        assert response[response_3] == response_3_value


@responses.activate
@pytest.mark.parametrize(
    "http_code, status, response_2, response_2_value, exception",
    [
        (200, True, "body", TEST_JSON, False),
        (401, False, "reason", "unauthorized", False),
        (403, False, "reason", "unauthorized", False),
        (404, False, "reason", "notFound", False),
        (1234, False, "reason", TEST_JSON["status"]["conditions"][0]["message"], False),
        (None, False, "reason", "NotAbleToCommunicateWithTheCluster ", True),
    ],
)
def test_get_capi_cluster(http_code, status, response_2, response_2_value, exception):
    if not exception:
        responses.get(
            CAPI_URI,
            json=TEST_JSON,
            status=http_code,
        )
    else:
        responses.get(
            CAPI_URI,
            body=Exception(""),
        )
    response = get_capi_cluster(NAME, NAMESPACE)
    assert response["status"] == status and response[response_2] == response_2_value


@pytest.fixture
def no_ambient_tls_config(monkeypatch, tmp_path):
    """Make the tests behave the same on a laptop and inside a pod."""
    monkeypatch.setattr(
        utils, "IN_CLUSTER_CA_FILE", str(tmp_path / "absent-ca.crt")
    )
    monkeypatch.delenv("KUBERNETES_CA_FILE", raising=False)
    monkeypatch.delenv("UNSAFE_SKIP_TLS_VERIFY", raising=False)


def test_tls_is_verified_by_default(no_ambient_tls_config):
    # True is what requests calls "verify against the system trust store"
    assert utils.tls_verify() is True


def usable_ca_bundle(tmp_path, name):
    """Return a path holding a bundle OpenSSL will actually load."""
    bundle = tmp_path / name
    bundle.write_bytes(open(certifi.where(), "rb").read())
    return str(bundle)


def test_in_cluster_ca_bundle_is_used_when_present(
    no_ambient_tls_config, monkeypatch, tmp_path
):
    ca_file = usable_ca_bundle(tmp_path, "ca.crt")
    monkeypatch.setattr(utils, "IN_CLUSTER_CA_FILE", ca_file)
    assert utils.tls_verify() == ca_file


def test_kubernetes_ca_file_wins(no_ambient_tls_config, monkeypatch, tmp_path):
    monkeypatch.setattr(
        utils, "IN_CLUSTER_CA_FILE", usable_ca_bundle(tmp_path, "in-cluster.crt"))
    configured = usable_ca_bundle(tmp_path, "configured.crt")
    monkeypatch.setenv("KUBERNETES_CA_FILE", configured)
    assert utils.tls_verify() == configured


def test_a_missing_ca_file_is_refused(no_ambient_tls_config, monkeypatch, tmp_path):
    missing = str(tmp_path / "missing.crt")
    monkeypatch.setenv("KUBERNETES_CA_FILE", missing)
    with pytest.raises(RuntimeError, match=missing):
        utils.tls_verify()


@pytest.mark.parametrize("content", ["", "   ", "not a pem\n", "-----BEGIN-----"])
def test_an_unusable_ca_bundle_is_refused(
    no_ambient_tls_config, monkeypatch, tmp_path, content
):
    """A path check alone would defer this to the first request."""
    bundle = tmp_path / "ca.crt"
    bundle.write_text(content)
    monkeypatch.setenv("KUBERNETES_CA_FILE", str(bundle))
    with pytest.raises(RuntimeError, match="unusable"):
        utils.tls_verify()


def test_a_ca_bundle_and_skip_verify_together_are_refused(
    no_ambient_tls_config, monkeypatch, tmp_path
):
    monkeypatch.setenv("KUBERNETES_CA_FILE", usable_ca_bundle(tmp_path, "ca.crt"))
    monkeypatch.setenv("UNSAFE_SKIP_TLS_VERIFY", "true")
    with pytest.raises(RuntimeError, match="conflict"):
        utils.tls_verify()


def test_a_missing_in_cluster_ca_is_refused(
    no_ambient_tls_config, monkeypatch, tmp_path
):
    """In a pod, an absent CA must not fall back to the public roots."""
    monkeypatch.setattr(utils, "IN_CLUSTER_CA_FILE", str(tmp_path / "absent.crt"))
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    with pytest.raises(RuntimeError, match="in-cluster CA"):
        utils.tls_verify()


def test_a_plaintext_endpoint_is_rejected_and_never_contacted(monkeypatch):
    """requests ignores verify for http, so the token would go out in clear."""
    contacted = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            contacted.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv(
            "KUBERNETES_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
        with pytest.raises(RuntimeError, match="must use https"):
            utils.kubernetes_base_url()
    finally:
        server.shutdown()

    assert contacted == []


@pytest.mark.parametrize("base_url", [
    "kubernetes.default.svc",
    "https://",
    "https://user:pass@api.example.com:6443",
    "https://api.example.com:6443?token=x",
    "https://api.example.com:6443#f",
    "https://api.example.com:not-a-port",
])
def test_an_unusable_endpoint_is_rejected(monkeypatch, base_url):
    monkeypatch.setenv("KUBERNETES_BASE_URL", base_url)
    with pytest.raises(RuntimeError):
        utils.kubernetes_base_url()


def test_a_trailing_slash_is_normalised(monkeypatch):
    monkeypatch.setenv("KUBERNETES_BASE_URL", "https://api.example.com:6443/")
    assert utils.kubernetes_base_url() == "https://api.example.com:6443"


@pytest.mark.parametrize(
    "value, verification_skipped",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
        ("  ", False),
        ("maybe", False),
    ],
)
def test_only_an_explicit_opt_in_skips_verification(
    no_ambient_tls_config, monkeypatch, value, verification_skipped
):
    monkeypatch.setenv("UNSAFE_SKIP_TLS_VERIFY", value)
    assert (utils.tls_verify() is False) == verification_skipped


@responses.activate
@pytest.mark.parametrize("verify", [True, "/etc/ssl/certs/test-ca.crt"])
def test_requests_carry_the_verify_setting(monkeypatch, verify):
    monkeypatch.setattr(utils, "TLS_VERIFY", verify)
    responses.get(CAPI_URI, json=TEST_JSON, status=200)
    get_capi_cluster(NAME, NAMESPACE)
    assert responses.calls[0].request.req_kwargs["verify"] == verify


@pytest.mark.parametrize(
    "environment, expected",
    [
        (
            {"KUBERNETES_BASE_URL": "https://api.example.com:6443"},
            "https://api.example.com:6443",
        ),
        (
            {"KUBERNETES_SERVICE_HOST": "10.96.0.1",
             "KUBERNETES_SERVICE_PORT": "443"},
            "https://10.96.0.1:443",
        ),
        ({"KUBERNETES_SERVICE_HOST": "fd00::1"}, "https://[fd00::1]:443"),
        ({"KUBERNETES_SERVICE_HOST": "[fd00::1]"}, "https://[fd00::1]:443"),
        ({}, "https://kubernetes.default.svc"),
    ],
)
def test_kubernetes_base_url(monkeypatch, environment, expected):
    for name in (
        "KUBERNETES_BASE_URL",
        "KUBERNETES_SERVICE_HOST",
        "KUBERNETES_SERVICE_PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert utils.kubernetes_base_url() == expected
