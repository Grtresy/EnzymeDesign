import json

from enzymedesign_bio_provider_adapters import DeterministicBioProviderAdapter
from enzymedesign_bio_provider_adapters import HttpBioProviderAdapter
from enzymedesign_bio_provider_adapters import locate_component_manifest
from enzymedesign_core import BIO_PROVIDER_PORT_CONTRACT_DIGEST
from openzyme_extension_spi import parse_component_manifest_json


def test_http_adapter_maps_exact_provider_responses_without_fallback() -> None:
    requests: list[tuple[str, str]] = []

    def read_json(url: str, **kwargs):
        requests.append((url, str(kwargs.get("method", "GET"))))
        if "uniprotkb" in url:
            return {
                "primaryAccession": "P12345",
                "sequence": {"length": 123},
                "proteinDescription": {
                    "recommendedName": {"fullName": {"value": "AOX"}}
                },
                "organism": {"scientificName": "Arabidopsis thaliana"},
            }
        if "rcsbsearch" in url:
            body = json.loads(kwargs["body"].decode("utf-8"))
            if body["query"]["parameters"]["value"] == "lysozyme":
                return {"result_set": [{"identifier": "1lyz"}]}
            return {}
        if "data.rcsb.org" in url:
            return {
                "struct": {"title": "Lysozyme"},
                "rcsb_entry_info": {"resolution_combined": [1.5]},
            }
        if "interpro" in url:
            return {
                "results": [
                    {
                        "metadata": {
                            "accession": "IPR000001",
                            "name": "Domain",
                            "type": "domain",
                        }
                    }
                ]
            }
        raise AssertionError(url)

    adapter = HttpBioProviderAdapter(
        json_reader=read_json,
        bytes_reader=lambda url, **kwargs: b">P12345\nMSEQUENCE\n",
    )

    protein = adapter.lookup_uniprot(accession="P12345")
    structure = adapter.search_rcsb_pdb(query="RCSB PDB lysozyme structure")[0]
    annotation = adapter.query_interpro(accession="P12345")
    asset = adapter.download_uniprot_fasta(accession="P12345")

    assert protein.name == "AOX"
    assert structure.structure_id == "1LYZ"
    assert annotation.entries[0]["entry_id"] == "IPR000001"
    assert asset.to_safe_dict()["content_digest"].startswith("sha256:")
    assert (
        requests.count(("https://rest.uniprot.org/uniprotkb/P12345?format=json", "GET"))
        == 1
    )


def test_fixture_adapter_is_explicitly_non_cutover() -> None:
    adapter = DeterministicBioProviderAdapter()

    assert adapter.lookup_uniprot(accession="P12345").metadata == {
        "fixture": True,
        "synthetic_source": True,
        "cutover_eligible": False,
        "scientific_status": "fixture_non_cutover",
    }
    assert (
        adapter.query_interpro(accession="P12345").entries[0]["scientific_status"]
        == "fixture_non_cutover"
    )


def test_adapter_manifest_implements_only_the_product_port() -> None:
    locator = locate_component_manifest()
    path = __import__(locator.resource_package, fromlist=["__name__"]).__path__[0]
    manifest = parse_component_manifest_json(
        open(f"{path}/{locator.resource_name}", encoding="utf-8").read()
    )

    assert manifest.manifest_digest == locator.manifest_digest
    assert (
        manifest.port_contracts[0].contract_digest == BIO_PROVIDER_PORT_CONTRACT_DIGEST
    )
    assert manifest.target_scoped is False
