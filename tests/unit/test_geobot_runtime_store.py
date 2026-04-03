import tempfile
import unittest
from pathlib import Path

from geobot_runtime.store import RuntimeStore


class RuntimeStoreTest(unittest.TestCase):
    def test_project_job_and_artifact_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            store = RuntimeStore(state_file)

            project = store.create_project(name="Demo")
            job = store.create_job(
                project.project_id,
                "template",
                "Population Map",
                workflow_type="teacher_flow",
            )
            store.append_job_step(job.job_id, "Queued", "Waiting")
            store.update_job_stage(job.job_id, "analysis", "success", "Parsed request")
            artifact = store.register_artifact(
                project.project_id,
                job.job_id,
                artifact_type="map_export",
                title="Population Map",
                path=str(Path(temp_dir) / "population.png"),
            )

            reloaded = RuntimeStore(state_file)
            self.assertEqual(reloaded.get_project(project.project_id).name, "Demo")
            self.assertEqual(reloaded.get_job(job.job_id).artifact_ids, [artifact.artifact_id])
            self.assertEqual(reloaded.get_job(job.job_id).workflow_type, "teacher_flow")
            self.assertEqual(reloaded.get_job(job.job_id).stages["analysis"]["status"], "success")
            self.assertEqual(reloaded.list_outputs(project.project_id)[0]["artifact_id"], artifact.artifact_id)


if __name__ == "__main__":
    unittest.main()
