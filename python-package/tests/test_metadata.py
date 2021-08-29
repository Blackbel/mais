import pytest
import ruamel.yaml as ryaml

from pathlib import Path
import shutil

from basedosdados import Metadata


DATASET_ID = "pytest"
TABLE_ID = "pytest"

METADATA_FILES = {
    "dataset": "dataset_config.yaml",
    "table": "table_config.yaml"
}


@pytest.fixture
def metadatadir(tmpdir_factory):
    (Path(__file__).parent / "tmp_bases").mkdir(exist_ok=True)
    return Path(__file__).parent / "tmp_bases"


@pytest.fixture
def dataset_metadata(metadatadir):
    return Metadata(
        dataset_id=DATASET_ID,
        metadata_path=metadatadir
    )
    

@pytest.fixture
def table_metadata(metadatadir):
    return Metadata(
        dataset_id=DATASET_ID,
        table_id=TABLE_ID,
        metadata_path=metadatadir
    )


@pytest.fixture
def dataset_metadata_path(metadatadir):
    return Path(metadatadir) / DATASET_ID


@pytest.fixture
def table_metadata_path(metadatadir):
    return Path(metadatadir) / DATASET_ID / TABLE_ID


@pytest.fixture
def out_of_date_metadata_obj(metadatadir):
    out_of_date_metadata = Metadata(
        dataset_id="br_me_rais",
        metadata_path=metadatadir
    )
    out_of_date_metadata.create(if_exists="replace")
    
    out_of_date_config = out_of_date_metadata.local_config
    out_of_date_config['metadata_modified'] = 'data_antiga'
    ryaml.dump(out_of_date_config, open(out_of_date_metadata.obj_path, "w"))
    
    return out_of_date_metadata


@pytest.fixture
def updated_metadata_obj(metadatadir):
    updated_metadata = Metadata(
        dataset_id="br_me_rais",
        metadata_path=metadatadir
    )
    updated_metadata.create(if_exists="replace")
    
    updated_config = updated_metadata.local_config
    updated_config['metadata_modified'] = updated_metadata.ckan_config['metadata_modified']
    ryaml.dump(updated_config, open(updated_metadata.obj_path, "w"))

    return updated_metadata


def test_create_from_dataset_id(dataset_metadata, dataset_metadata_path):
    shutil.rmtree(dataset_metadata_path, ignore_errors=True)
    dataset_metadata.create()
    assert (dataset_metadata_path / METADATA_FILES['dataset']).exists()


def test_create_from_dataset_and_table_id(table_metadata, table_metadata_path):
    shutil.rmtree(table_metadata_path, ignore_errors=True)
    table_metadata.create()
    assert (table_metadata_path / METADATA_FILES['table']).exists()


def test_create_if_exists_raise(dataset_metadata, table_metadata):
    
    with pytest.raises(FileExistsError):
        dataset_metadata.create(if_exists="raise")

    with pytest.raises(FileExistsError):
        table_metadata.create(if_exists="raise")
    

def test_create_if_exists_replace(
    dataset_metadata,
    dataset_metadata_path,
    table_metadata,
    table_metadata_path
    ):
    dataset_metadata.create(if_exists="replace")
    assert (dataset_metadata_path / METADATA_FILES['dataset']).exists()

    table_metadata.create(if_exists="replace")
    assert (table_metadata_path / METADATA_FILES['table']).exists()


def test_create_if_exists_pass(
    dataset_metadata,
    dataset_metadata_path,
    table_metadata,
    table_metadata_path
    ):

    dataset_metadata.create(if_exists="replace")
    assert (dataset_metadata_path / METADATA_FILES['dataset']).exists()

    table_metadata.create(if_exists="replace")
    assert (table_metadata_path / METADATA_FILES['table']).exists()    


def test_create_columns(table_metadata, table_metadata_path):
    shutil.rmtree(table_metadata_path, ignore_errors=True)
    table_metadata.create(columns=["coluna1", "coluna2"])
    assert(table_metadata_path / METADATA_FILES['table']).exists()
    

def test_create_partition_columns():
    pass


def test_create_force_columns():
    pass


def test_is_updated_is_true(updated_metadata_obj):
    assert updated_metadata_obj.is_updated() == True


def test_is_updated_is_false(out_of_date_metadata_obj):
    assert out_of_date_metadata_obj.is_updated() == False


def test_validate_is_succesful():
    pass


def test_validate_raise_error():
    pass


def test_publish():
    pass