from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import yaml


class RegistryError(RuntimeError):
    """Raised when registry data is missing or inconsistent."""


@dataclass(frozen=True)
class Registry:
    project_root: Path
    plugins: dict[str, dict[str, Any]]
    parameters: dict[str, dict[str, Any]]
    workflows: dict[str, dict[str, Any]]
    materials: dict[str, dict[str, Any]]
    profiles: dict[str, dict[str, Any]]

    @classmethod
    def from_project_root(cls, project_root: Path | str) -> "Registry":
        root = Path(project_root).resolve()
        plugins = cls._load_plugins(root / "plugins")
        parameters = cls._load_parameter_registry(root / "plugins")
        workflows = cls._load_named_yaml(root / "plugins", "workflows")
        materials = cls._load_yaml_dir(root / "materials", key_field="id")
        if not materials:
            materials = cls._load_yaml_dir(root / "config" / "materials", key_field="id")
        profiles = cls._load_yaml_dir(root / "profiles", key_field="id")
        return cls(root, plugins, parameters, workflows, materials, profiles)

    def plugin_ids(self) -> list[str]:
        return sorted(self.plugins)

    def get_parameter(self, parameter_id: str) -> dict[str, Any]:
        try:
            return self.parameters[parameter_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown parameter: {parameter_id}") from exc

    def resolve_parameters(
        self,
        *,
        software: str,
        workflow: str,
        material: str,
        profile: str,
    ) -> dict[str, dict[str, Any]]:
        workflow_data = self._get(self.workflows, workflow, "workflow")
        material_data = self._get(self.materials, material, "material")
        profile_data = self._get(self.profiles, profile, "profile")

        if workflow_data.get("software") != software:
            raise RegistryError(f"Workflow {workflow} does not belong to {software}")

        resolved: dict[str, dict[str, Any]] = {}
        for parameter_id in workflow_data.get("uses", []):
            parameter = self.get_parameter(parameter_id)
            resolved[parameter_id] = {
                "value": parameter.get("default"),
                "source": "parameter-default",
                "metadata": parameter,
            }

        self._apply_overrides(resolved, workflow_data.get("parameters", {}), f"workflow:{workflow}")
        self._apply_overrides(resolved, material_data.get("parameters", {}), f"material:{material}")
        self._apply_overrides(resolved, profile_data.get("parameters", {}), f"profile:{profile}")
        return resolved

    def resolve_parameters_strict(
        self,
        *,
        software: str,
        workflow: str,
        material: str,
        profile: str,
    ) -> dict[str, dict[str, Any]]:
        """Like resolve_parameters but warns on unrecognised override keys."""
        import warnings

        workflow_data = self._get(self.workflows, workflow, "workflow")
        material_data = self._get(self.materials, material, "material")
        profile_data = self._get(self.profiles, profile, "profile")

        resolved = self.resolve_parameters(
            software=software, workflow=workflow, material=material, profile=profile
        )

        # Check for unrecognised override keys
        known_ids = set(resolved.keys())
        for source_name, source_dict in [
            (f"workflow:{workflow}", workflow_data.get("parameters", {})),
            (f"material:{material}", material_data.get("parameters", {})),
            (f"profile:{profile}", profile_data.get("parameters", {})),
        ]:
            for key in source_dict:
                if key not in known_ids:
                    warnings.warn(
                        f"{source_name}: override key '{key}' not in workflow 'uses' list — "
                        f"may be a typo or missing parameter definition. "
                        f"This override is silently ignored by resolve_parameters.",
                        stacklevel=2,
                    )
        return resolved

    def render_template(
        self,
        *,
        software: str,
        workflow: str,
        material: str,
        profile: str,
        template_rel: str | None = None,
    ) -> str:
        """Resolve parameters and render a Jinja2 template.

        If *template_rel* is not given, the first template listed in the
        workflow's ``templates`` key is used.
        """
        resolved = self.resolve_parameters(
            software=software,
            workflow=workflow,
            material=material,
            profile=profile,
        )
        workflow_data = self._get(self.workflows, workflow, "workflow")

        if template_rel is None:
            try:
                template_rel = workflow_data["templates"][0]
            except (KeyError, IndexError) as exc:
                raise RegistryError(
                    f"Workflow {workflow} has no templates defined"
                ) from exc

        template_path = self.project_root / "plugins" / software / template_rel
        if not template_path.is_file():
            raise RegistryError(f"Template not found: {template_path}")

        material_data = self._get(self.materials, material, "material")
        profile_data = self._get(self.profiles, profile, "profile")
        namespace = _build_nested_namespace(resolved)
        namespace["material"] = material_data
        namespace["profile"] = profile_data
        namespace["workflow_meta"] = workflow_data
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_path.parent)),
            undefined=jinja2.StrictUndefined,
        )
        tpl = env.get_template(template_path.name)
        return tpl.render(**namespace)

    def render_all_templates(
        self,
        *,
        software: str,
        workflow: str,
        material: str,
        profile: str,
        output_dir: Path | str,
    ) -> dict[str, Path]:
        """Render all templates for a workflow into *output_dir*.

        Returns a dict mapping template name → written file path.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        resolved = self.resolve_parameters(
            software=software,
            workflow=workflow,
            material=material,
            profile=profile,
        )
        workflow_data = self._get(self.workflows, workflow, "workflow")
        templates = workflow_data.get("templates", [])

        if not templates:
            raise RegistryError(f"Workflow {workflow} has no templates defined")

        material_data = self._get(self.materials, material, "material")
        profile_data = self._get(self.profiles, profile, "profile")
        namespace = _build_nested_namespace(resolved)
        namespace["material"] = material_data
        namespace["profile"] = profile_data
        namespace["workflow_meta"] = workflow_data

        rendered: dict[str, Path] = {}
        for template_rel in templates:
            template_path = self.project_root / "plugins" / software / template_rel
            if not template_path.is_file():
                raise RegistryError(f"Template not found: {template_path}")

            # Derive output filename from template name
            stem = template_path.stem  # e.g. "scf" from "scf.in.j2"
            # Strip trailing ".in" if present, then add ".in"
            if stem.endswith(".in"):
                out_name = stem + ""  # keep as-is
            else:
                out_name = stem + ".in"

            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(template_path.parent)),
                undefined=jinja2.StrictUndefined,
            )
            tpl = env.get_template(template_path.name)
            content = tpl.render(**namespace)

            out_file = output_path / out_name
            out_file.write_text(content, encoding="utf-8")
            rendered[out_name] = out_file

            # Stage-specific subdirectory support: if workflow has named stages,
            # also write into stage-named subdirs (one template per stage)
            stages = workflow_data.get("stages", [])
            for stage in stages:
                if stage.get("template") == template_rel:
                    stage_dir = output_path / stage["id"]
                    stage_dir.mkdir(parents=True, exist_ok=True)
                    stage_file = stage_dir / out_name
                    stage_file.write_text(content, encoding="utf-8")
                    rendered[f"{stage['id']}/{out_name}"] = stage_file

        return rendered

    @staticmethod
    def _apply_overrides(
        resolved: dict[str, dict[str, Any]],
        overrides: dict[str, Any],
        source: str,
    ) -> None:
        for parameter_id, value in overrides.items():
            if parameter_id not in resolved:
                continue
            resolved[parameter_id]["value"] = value
            resolved[parameter_id]["source"] = source

    @staticmethod
    def _get(collection: dict[str, dict[str, Any]], key: str, label: str) -> dict[str, Any]:
        try:
            return collection[key]
        except KeyError as exc:
            raise RegistryError(f"Unknown {label}: {key}") from exc

    @staticmethod
    def _load_plugins(plugins_dir: Path) -> dict[str, dict[str, Any]]:
        plugins: dict[str, dict[str, Any]] = {}
        for plugin_file in sorted(plugins_dir.glob("*/plugin.yaml")):
            data = _read_yaml(plugin_file)
            plugin_id = data.get("id")
            if not plugin_id:
                raise RegistryError(f"Plugin missing id: {plugin_file}")
            plugins[plugin_id] = data
        return plugins

    @staticmethod
    def _load_parameter_registry(plugins_dir: Path) -> dict[str, dict[str, Any]]:
        parameters: dict[str, dict[str, Any]] = {}
        for parameter_file in sorted(plugins_dir.glob("*/parameters/*.yaml")):
            data = _read_yaml(parameter_file)
            entries = data.get("parameters", [])
            for parameter in entries:
                parameter_id = parameter.get("id")
                if not parameter_id:
                    raise RegistryError(f"Parameter missing id: {parameter_file}")
                parameters[parameter_id] = parameter
        return parameters

    @staticmethod
    def _load_named_yaml(root: Path, subdir: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for yaml_file in sorted(root.glob(f"*/{subdir}/*.yaml")):
            data = _read_yaml(yaml_file)
            record_id = data.get("id")
            if not record_id:
                raise RegistryError(f"Record missing id: {yaml_file}")
            records[record_id] = data
        return records

    @staticmethod
    def _load_yaml_dir(directory: Path, *, key_field: str) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        if not directory.exists():
            return records
        for yaml_file in sorted(directory.glob("*.yaml")):
            data = _read_yaml(yaml_file)
            record_id = data.get(key_field)
            if not record_id:
                raise RegistryError(f"Record missing {key_field}: {yaml_file}")
            records[record_id] = data
        return records


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"YAML root must be a mapping: {path}")
    return data


def _build_nested_namespace(resolved: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Convert flat parameter-IDs into a nested dict for Jinja2 templates.

    ``qe.pw.system.ecutwfc`` → ``{"qe": {"pw": {"system": {"ecutwfc": 80}}}}``
    """
    namespace: dict[str, Any] = {}
    for param_id, entry in resolved.items():
        parts = param_id.split(".")
        node = namespace
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = entry["value"]
    return namespace
