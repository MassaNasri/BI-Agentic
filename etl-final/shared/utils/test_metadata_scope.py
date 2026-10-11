from shared.utils.metadata_schema import MetadataSchema


def test_scope_fields_copies_only_present_immutable_scope():
    message = {
        "workspace_id": 23,
        "dataset_id": "dataset-91",
        "ingestion_job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "password": "must-not-propagate",
    }

    assert MetadataSchema.scope_fields(message) == {
        "workspace_id": 23,
        "dataset_id": "dataset-91",
        "ingestion_job_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }


def test_scope_fields_does_not_invent_missing_scope():
    assert MetadataSchema.scope_fields({"workspace_id": 23}) == {"workspace_id": 23}
    assert MetadataSchema.scope_fields(None) == {}
