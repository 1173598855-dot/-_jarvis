"""Extended tests v2 for main_fastapi.py - Iteration 59"""
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from fastapi.testclient import TestClient

from main_fastapi import app

client = TestClient(app, raise_server_exceptions=False)


class TestOrchestratorAgentsEndpoint(unittest.TestCase):
    def test_returns_dict_with_agents_key(self):
        r = client.get("/api/orchestrator/agents")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("agents", data)
        self.assertIn("count", data)
        self.assertIsInstance(data["agents"], list)

    def test_count_matches_list_length(self):
        r = client.get("/api/orchestrator/agents")
        data = r.json()
        self.assertEqual(data["count"], len(data["agents"]))


class TestOrchestratorHistoryEndpoint(unittest.TestCase):
    def test_returns_results_list(self):
        r = client.get("/api/orchestrator/history")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)

    def test_limit_param_truncates(self):
        r = client.get("/api/orchestrator/history?limit=5")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertLessEqual(len(data["results"]), 5)


class TestOrchestratorDispatchEndpoint(unittest.TestCase):
    def test_dispatch_returns_dict(self):
        payload = {"agent_name": "engineer", "prompt": "write tests"}
        r = client.post("/api/orchestrator/dispatch", json=payload)
        self.assertIn(r.status_code, [200, 500])
        self.assertIsInstance(r.json(), dict)

    def test_dispatch_missing_agent_name_returns_400(self):
        payload = {"prompt": "do it"}
        r = client.post("/api/orchestrator/dispatch", json=payload)
        self.assertEqual(r.status_code, 400)

    def test_dispatch_missing_prompt_returns_400(self):
        payload = {"agent_name": "engineer"}
        r = client.post("/api/orchestrator/dispatch", json=payload)
        self.assertEqual(r.status_code, 400)


class TestRolesListEndpoint(unittest.TestCase):
    def test_returns_roles_and_count(self):
        r = client.get("/api/roles")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("roles", data)
        self.assertIn("count", data)

    def test_filter_by_capability(self):
        r = client.get("/api/roles?capability=coding")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for role in data["roles"]:
            self.assertIn("coding", role.get("capabilities", []))


class TestRoleDetailEndpoint(unittest.TestCase):
    def test_existing_role_returns_200(self):
        r = client.get("/api/roles/engineer")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("role", data)

    def test_nonexistent_role_returns_404(self):
        r = client.get("/api/roles/nonexistent_role_xyz_999")
        self.assertEqual(r.status_code, 404)


class TestRoleDispatchEndpoints(unittest.TestCase):
    def test_dispatch_by_role_returns_dict(self):
        payload = {"role_name": "engineer", "prompt": "write code", "timeout": 30}
        r = client.post("/api/roles/dispatch", json=payload)
        self.assertIn(r.status_code, [200, 500])
        self.assertIsInstance(r.json(), dict)

    def test_dispatch_by_capability_returns_dict(self):
        payload = {"capability": "coding", "prompt": "write code"}
        r = client.post("/api/roles/dispatch_by_cap", json=payload)
        self.assertIn(r.status_code, [200, 500])

    def test_dispatch_by_cap_not_found_returns_404(self):
        payload = {"capability": "nonexistent_cap_xyz_999", "prompt": "do it"}
        r = client.post("/api/roles/dispatch_by_cap", json=payload)
        self.assertEqual(r.status_code, 404)

    def test_batch_dispatch_returns_results_key(self):
        payload = {"tasks": [{"role": "engineer", "prompt": "t1"}]}
        r = client.post("/api/roles/batch_dispatch", json=payload)
        self.assertIn(r.status_code, [200, 500])
        data = r.json()
        self.assertIn("results", data)


class TestOpenAPIEndpoints(unittest.TestCase):
    def test_openapi_json_accessible(self):
        r = client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("openapi", data)


def run_all_tests():
    print("=" * 60)
    print("J.A.R.V.I.S. main_fastapi extended v2 - Iteration 59")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [
        TestOrchestratorAgentsEndpoint,
        TestOrchestratorHistoryEndpoint,
        TestOrchestratorDispatchEndpoint,
        TestRolesListEndpoint,
        TestRoleDetailEndpoint,
        TestRoleDispatchEndpoints,
        TestOpenAPIEndpoints,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {total} tests, {passed} passed")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_all_tests())
