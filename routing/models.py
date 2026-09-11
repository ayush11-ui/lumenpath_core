from django.db import models
import uuid


class StreetSegment(models.Model):
    """One directed/undirected edge in the mock-city street graph.

    Every segment connects a start node to an end node (both expressed as
    lat/lng pairs). The routing engine treats the graph as *undirected*
    (pedestrians can walk either direction along a street), so each row is
    a traversable street block.

    Safety attributes:
      * lighting_score : 1 (pitch black) .. 10 (brightly lit)
      * crime_rate     : 1 (very safe)   .. 10 (high crime)
    """

    name = models.CharField(max_length=128)
    start_lat = models.FloatField()
    start_lng = models.FloatField()
    end_lat = models.FloatField()
    end_lng = models.FloatField()
    lighting_score = models.IntegerField(choices=[(i, i) for i in range(1, 11)])
    crime_rate = models.IntegerField(choices=[(i, i) for i in range(1, 11)])
    distance_meters = models.FloatField(help_text="Length of the block in meters.")

    # Exact node → segment bookkeeping. We denormalise rounded coordinates so
    # the Dijkstra graph can match "node A == node B" reliably even when two
    # segments come from different source rows.
    start_key = models.CharField(max_length=32, db_index=True, editable=False)
    end_key = models.CharField(max_length=32, db_index=True, editable=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Auto-compute node keys from coordinates before persisting."""
        self.start_key = self._node_key(self.start_lat, self.start_lng)
        self.end_key = self._node_key(self.end_lat, self.end_lng)
        super().save(*args, **kwargs)

    @staticmethod
    def _node_key(lat, lng, precision=6):
        """Round coordinates and join them into a stable, matchable string."""
        return f"{round(lat, precision)},{round(lng, precision)}"


class SafeZone(models.Model):
    """Point-of-safety landmark shown as pins on the map."""

    zone_type_choices = [
        ("Police", "Police"),
        ("Hospital", "Hospital"),
        ("24/7 Store", "24/7 Store"),
    ]

    name = models.CharField(max_length=128)
    zone_type = models.CharField(max_length=16, choices=zone_type_choices)
    lat = models.FloatField()
    lng = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.zone_type})"


class Incident(models.Model):
    """An incident marker reported by users (e.g. dim street, suspicious activity).

    Seeded with three demo entries by `seed_data` so the map / heatmap layer has
    real content during the live presentation.
    """

    severity_choices = [("Low", "Low"), ("Medium", "Medium"), ("High", "High")]

    type = models.CharField(max_length=128, default="Reported")
    severity = models.CharField(max_length=16, choices=severity_choices, default="Medium")
    description = models.CharField(max_length=500, blank=True)
    lat = models.FloatField()
    lng = models.FloatField()
    reported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} ({self.severity})"


class TrackingSession(models.Model):
    """A live tracking session started by the "Start Safe Navigation" button.

    The frontend updates `current_lat` / `current_lng` in real time while the
    user walks the safe route, allowing other screens (e.g. a watch party) to
    share the live track.
    """

    session_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    active = models.BooleanField(default=True)
    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)
    destination_lat = models.FloatField()
    destination_lng = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session {self.session_token} {'active' if self.active else 'closed'}"