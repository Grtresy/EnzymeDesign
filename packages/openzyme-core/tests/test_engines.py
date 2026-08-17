from openzyme_core import EngineDescriptor
from openzyme_core import EngineRegistry


class FakeEngine:
    descriptor = EngineDescriptor(
        engine_name="fake_engine",
        tool_names=("fake.start", "fake.status"),
        input_schema={"type": "object", "required": ["brief"]},
        output_schema={"type": "object", "required": ["summary"]},
        requires_approval=False,
        supports_background=True,
        idempotency_key_shape="{task_id}:fake_engine:{nonce}",
        produces_file_types=("research_dossier",),
        capability_key="fake",
    )

    def register_tools(self, registry: object) -> None:
        del registry


def test_engine_registry_tracks_descriptors() -> None:
    registry = EngineRegistry()
    registry.register(FakeEngine())

    engine = registry.require("fake_engine")
    descriptors = registry.list_descriptors()

    assert engine.descriptor.capability_key == "fake"
    assert descriptors[0].to_dict()["engine_name"] == "fake_engine"
    assert registry.list_engines()[0].descriptor.engine_name == "fake_engine"
