"""Locust load-testing scenario for HydroPulse AI endpoints."""

from locust import HttpUser, between, task


class HydroPulseUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def test_health(self):
        self.client.get("/api/v1/health")

    @task(3)
    def test_stations(self):
        self.client.get("/api/v1/stations")

    @task(5)
    def test_forecast(self):
        self.client.get("/api/v1/stations/damodar_ramgarh/forecast?days=7")

    @task(4)
    def test_history(self):
        self.client.get("/api/v1/stations/damodar_bokaro/history?days=30")

    @task(5)
    def test_risk_map(self):
        self.client.get("/api/v1/risk/map")

    @task(4)
    def test_alerts(self):
        self.client.get("/api/v1/alerts")

    @task(3)
    def test_water_quality(self):
        self.client.get("/api/v1/water-quality/damodar_dhanbad")

    @task(3)
    def test_drought(self):
        self.client.get("/api/v1/drought/subarnarekha_jamshedpur")

    @task(2)
    def test_metrics(self):
        self.client.get("/api/v1/model/metrics")
