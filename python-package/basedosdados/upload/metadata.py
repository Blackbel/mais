import os
import json
import sys
import ast
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
from collections import defaultdict

import requests
import ruamel.yaml as ryaml

from google.api_core.exceptions import NotFound

import ckanapi
from ckanapi import RemoteCKAN
from ckanapi import errors

from basedosdados.upload.base import Base
from basedosdados.exceptions import BaseDosDadosException

# CKAN_URL = os.environ.get("CKAN_URL", "http://localhost:5000")
CKAN_URL = "http://0.0.0.0:5000"
CKAN_URL_STAGING = "http://staging.basedosdados.org"


class Metadata(Base):
    def __init__(self, dataset_id, table_id=None, **kwargs):
        super().__init__(**kwargs)

        self.dataset_id = dataset_id
        self.table_id = table_id

    @property
    def obj_path(self):

        if self.table_id is None:
            return self.metadata_path / self.dataset_id / "dataset_config.yaml"
        else:
            return (
                self.metadata_path
                / self.dataset_id
                / self.table_id
                / "table_config.yaml"
            )

    @property
    def local_config(self):
        if self.obj_path.exists():
            return ryaml.safe_load(open(self.obj_path, "r").read())
        else:
            return {}

    @property
    @lru_cache(256)
    def ckan_config(self) -> dict:

        # TODO: This will not be needed after migration
        pkg_list = requests.get(CKAN_URL_STAGING + "/api/3/action/package_list").json()[
            "result"
        ]

        if self.dataset_id in pkg_list:
            dataset_id = self.dataset_id
        elif self.dataset_id.replace("_", "-") in pkg_list:
            dataset_id = self.dataset_id.replace("_", "-")
        else:
            return defaultdict(lambda: dict())

        dataset_config = requests.get(
            CKAN_URL_STAGING + f"/api/3/action/package_show?id={dataset_id}"
        ).json()["result"]

        # unpack extras
        dataset_args = [
            d for d in dataset_config["extras"] if d["key"] == "dataset_args"
        ]
        if dataset_args:
            dataset_args = dataset_args[0]["value"]
            dataset_config.update(dataset_args)

        if self.table_id is not None:
            return [
                r for r in dataset_config["resources"] if r["name"] == self.table_id
            ][0]

        else:
            return dataset_config

    @property
    @lru_cache(256)
    def columns_schema(self) -> dict:
        """Returns a dictionary with the schema of the columns.

        Returns:
        """

        return requests.get(CKAN_URL + "/api/3/action/bd_bdm_columns_schema").json()[
            "result"
        ]

    @property
    @lru_cache(256)
    def metadata_schema(self):
        """Get metadata schema from CKAN API endpoint.

        Returns:
        """

        dataset_schema = requests.get(
            CKAN_URL + "/api/3/action/bd_dataset_schema"
        ).json()["result"]
        table_schema = requests.get(
            CKAN_URL + "/api/3/action/bd_bdm_table_schema"
        ).json()["result"]

        if self.table_id is None:
            return dataset_schema
        else:
            return table_schema

    def is_updated(self):

        if self.local_config.get("metadata_modified") is None:
            return False
        else:
            return self.ckan_config.get("metadata_modified") == self.local_config.get(
                "metadata_modified"
            )

    def create(
        self, if_exists="raise", columns=[], partition_columns=[], force_columns=False
    ):
        """Create metadata file based on the current version saved to
        CKAN database

        Args:
            if_exists (str): Optional. What to do if config exists
                * raise : Raises Conflict exception
                * replace : Replaces config file with most recent
                * pass : Do nothing
            columns (list): Optional.
                A `list` with the table columns' names.
            partition_columns(list): Optional.
                A `list` with the name of the table columns that partition the data.
            force_columns (bool): Optional.
                If set to `True`, overwrite CKAN's columns with the ones provided.
                If set to `False`, keep CKAN's columns instead of the ones provided.
        """

        if self.obj_path.exists() and if_exists == "raise":
            raise FileExistsError(
                f"{self.obj_path} already exists. Set the arg `if_exists`"
                " to `replace` to replace it."
            )
        elif if_exists != "pass":

            data = self.ckan_config

            # adds local columns if 1. columns is empty and 2. force_columns is True
            if (not data.get("columns")) or force_columns == True:
                data["columns"] = [{"name": c} for c in columns]

            yaml_obj = builds_yaml_object(
                self.metadata_schema, data, columns_schema=self.columns_schema
            )
            self.obj_path.parent.mkdir(parents=True, exist_ok=True)

            ruamel = ryaml.YAML()
            ruamel.preserve_quotes = True
            ruamel.indent(mapping=4, sequence=6, offset=4)
            ruamel.dump(yaml_obj, open(self.obj_path, "w"))

        return self

    def validate(self):
        """Validate dataset_config.yaml or table_config.yaml files. 
        The yaml file should be located at metadata_path/dataset_id[/table_id/],
        as defined in your config.toml

        Raises:
            BaseDosDadosException: when the file has validation errors.

        """
        error_dict = {}

        data_dict = build_validate_dict(
            self.dataset_id, self.table_id, self.metadata_path
        )
        
        bdm_ckan = RemoteCKAN(
            CKAN_URL, user_agent="", apikey=None
        )

        response = bdm_ckan.action.package_validate(**data_dict)

        if response['errors'] != []:
            error_dict[self.ckan_config["name"]] = response['errors']
        else:
            return True

        if error_dict:
            raise BaseDosDadosException(
                f"{self.obj_path} has validation errors: {error_dict}"
            )


def handle_data(k, schema, data, local_default=None):

    # If no data is found for that key, uses pydantic default, else uses
    # local default

    selected = data.get(k)
    if not selected:
        selected = schema[k].get("user_input_hint", local_default)

    # In some cases like `tags`, `groups`, `organization`
    # the API default is to return a dict or list[dict] with all info.
    # But, we just use `name` to build the yaml
    _selected = deepcopy(selected)
    if not isinstance(_selected, list):
        _selected = [_selected]
    if isinstance(_selected[0], dict):
        if _selected[0].get("id") is not None:
            return [s.get("name") for s in _selected]

    return selected


def handle_complex_fields(yaml_obj, k, properties, definitions, data):
    yaml_obj[k] = ryaml.CommentedMap()
    # Parsing 'allOf': [{'$ref': '#/definitions/PublishedBy'}]
    # To get PublishedBy
    d = properties[k]["allOf"][0]["$ref"].split("/")[-1]
    if "properties" in definitions[d].keys():
        for dk, dv in definitions[d]["properties"].items():
            yaml_obj[k][dk] = handle_data(dk, definitions[d]["properties"], data.get(k))

    return yaml_obj


def builds_yaml_object(schema, data=dict(), columns_schema=dict()):
    def comment_treatment(c):
        if COLUMNS:
            return None
        else:
            return "\n" + "".join(c.get("description", [""]))

    COLUMNS = False
    yaml_obj = ryaml.CommentedMap()

    properties, definitions = schema["properties"], schema["definitions"]

    # Drops all properties without yaml_order
    key_list = list(properties.keys())
    for k in key_list:
        if properties[k].get("yaml_order") is None:
            del properties[k]

    # Recursivelly adds properties to yaml to maintain order
    def _add_property(yaml_obj, properties, goal=None):

        for k in properties.keys():

            # Base case (goal is None) has to look for id_before == None
            # Otherwise just looks for key
            if ((goal is None) & (properties[k]["yaml_order"]["id_before"] == goal)) | (
                k == goal
            ):

                if "allOf" in properties[k] and (data.get(k) is not None):

                    yaml_obj = handle_complex_fields(
                        yaml_obj, k, properties, definitions, data
                    )

                else:
                    yaml_obj[k] = handle_data(k, properties, data)

                # Adds comments
                yaml_obj.yaml_set_comment_before_after_key(
                    k, before=comment_treatment(properties[k])
                )
                break

        # Returns ruaml object when property doesn't point to any other property
        id_after = properties[k]["yaml_order"]["id_after"]
        if id_after is None:
            return yaml_obj
        elif id_after not in properties.keys():
            raise BaseDosDadosException(
                f"Inconsistent YAML ordering: {id_after} is pointed to by {k}"
                f" but doesn't have itself a `yaml_order` field in the JSON S"
                f"chema."
            )
        else:
            properties.pop(k)
            return _add_property(yaml_obj, properties, id_after)

    yaml_obj = _add_property(yaml_obj, properties)

    if data.get("columns"):
        COLUMNS = True
        properties, definitions = (
            columns_schema["properties"],
            columns_schema["definitions"],
        )

        yaml_obj["columns"] = []
        for data in data.get("columns"):
            prop = deepcopy(properties)
            yaml_obj["columns"].append(_add_property(ryaml.CommentedMap(), prop))

    return yaml_obj


def get_bdm_ckan_metadata(dataset_id, table_id=None):

    endpoint_url = (
        f"{CKAN_URL_STAGING}/api/3/action/bd_bdm_dataset_show?dataset_id="
        f"{dataset_id}"
    )
    bdm_ckan_dataset_metadata = requests.get(endpoint_url).json()["result"]

    if table_id:
        endpoint_url = (
            f"{CKAN_URL_STAGING}/api/3/action/bd_bdm_table_show?dataset_i"
            f"d={dataset_id}&table_id={table_id}"
        )
        bdm_ckan_table_metadata = requests.get(endpoint_url).json()["result"]

    else: 
        bdm_ckan_table_metadata = None
    
    return bdm_ckan_dataset_metadata, bdm_ckan_table_metadata


def build_validate_dict(dataset_id, table_id=None, metadata_path=None):
    """
    Helper function to structure local config files data for validation.

    Args:
        dataset_id (str):
            The dataset_id that corresponds to the data subject to validation.
    
    Returns:
        dict
    """


    bdm_ckan_dataset_metadata, bdm_ckan_table_metadata = get_bdm_ckan_metadata(dataset_id, table_id)    
    dataset_metadata = Metadata(
        dataset_id=dataset_id, metadata_path=metadata_path
    )

    if table_id:
        table_metadata = Metadata(
            dataset_id=dataset_id,
            table_id=table_id,
            metadata_path=metadata_path
        )

        data = {
            "name": bdm_ckan_dataset_metadata["name"],
            "type": bdm_ckan_dataset_metadata["type"],
            "title": bdm_ckan_dataset_metadata["title"],
            "private": bdm_ckan_dataset_metadata["private"],
            "owner_org": bdm_ckan_dataset_metadata["owner_org"],
            "resources": [
                {
                    "name": bdm_ckan_table_metadata["name"],
                    "resource_type": bdm_ckan_table_metadata["resource_type"],
                    "table_id": table_metadata.local_config["table_id"]
                }
            ]
        }

    else:
        data = {
            "name": dataset_metadata.local_config["dataset_id"].replace("_", "-"),
            "type": bdm_ckan_dataset_metadata["type"],
            "title": dataset_metadata.local_config["title"],
            "private": bdm_ckan_dataset_metadata["private"],
            "owner_org": bdm_ckan_dataset_metadata["owner_org"],
            "resources": bdm_ckan_dataset_metadata["resources"]
        }
    
    return data