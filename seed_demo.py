import secrets

from werkzeug.security import generate_password_hash

from app import APP_ENV, app, get_db, init_db, utcnow


DEMO_USERS = (
    ("Demo Resident", "demo.resident@warbridge.local", "DISPLACED", "female", 1),
    ("Demo NGO", "demo.ngo@warbridge.local", "NGO", None, 1),
    ("Demo Host", "demo.host@warbridge.local", "HOST", None, 1),
    ("Pending Demo NGO", "pending.ngo@warbridge.local", "NGO", None, 0),
    ("Demo Administrator", "demo.admin@warbridge.local", "ADMIN", None, 1),
)


def seed_demo_data():
    if APP_ENV != "development":
        raise SystemExit("Demo data can only be seeded when WARBRIDGE_ENV=development.")

    with app.app_context():
        init_db()
        db = get_db()
        db.execute(
            """CREATE TABLE IF NOT EXISTS demo_seed (
                   id INTEGER PRIMARY KEY CHECK(id=1),
                   seeded_at TEXT NOT NULL
               )"""
        )
        if db.execute("SELECT 1 FROM demo_seed WHERE id=1").fetchone():
            print("Demo data is already present; no changes were made.")
            return

        emails = tuple(user[1] for user in DEMO_USERS)
        placeholders = ",".join("?" for _ in emails)
        existing = db.execute(
            f"SELECT email FROM users WHERE email IN ({placeholders})", emails
        ).fetchall()
        if existing:
            raise SystemExit(
                "A demo account already exists without the seed marker. "
                "Use a fresh WARBRIDGE_DB path to avoid changing existing accounts."
            )

        password = secrets.token_urlsafe(18)
        password_hash = generate_password_hash(password)
        now = utcnow()
        db.execute("BEGIN IMMEDIATE")
        try:
            user_ids = {}
            for name, email, role, gender, verified in DEMO_USERS:
                cursor = db.execute(
                    """INSERT INTO users(name,email,password_hash,role,gender,verified,blocked,created_at)
                       VALUES(?,?,?,?,?,?,0,?)""",
                    (name, email, password_hash, role, gender, verified, now),
                )
                user_ids[email] = cursor.lastrowid

            resident_id = user_ids["demo.resident@warbridge.local"]
            ngo_id = user_ids["demo.ngo@warbridge.local"]
            host_id = user_ids["demo.host@warbridge.local"]
            pending_ngo_id = user_ids["pending.ngo@warbridge.local"]
            admin_id = user_ids["demo.admin@warbridge.local"]

            shelter_cursor = db.execute(
                """INSERT INTO shelters(
                       ngo_id,name,city,area,address,beds_available,women_safe,
                       family_friendly,verified,blocked,closed,updated_at
                   ) VALUES(?,?,?,?,?,4,1,1,1,0,0,?)""",
                (ngo_id, "Demo Community Shelter", "Jaipur", "Training District",
                 "Demo Lane, Training District", now),
            )
            shelter_id = shelter_cursor.lastrowid
            db.execute(
                """INSERT INTO shelters(
                       ngo_id,name,city,area,address,beds_available,verified,updated_at
                   ) VALUES(?,?,?,?,?,3,0,?)""",
                (pending_ngo_id, "Pending Demo Shelter", "Jaipur", "Training District",
                 "Demo Lane, Training District", now),
            )

            accommodation_cursor = db.execute(
                """INSERT INTO accommodations(
                       host_id,city,area,address,rooms,rooms_available,women_only,
                       description,verified,blocked,closed,updated_at
                   ) VALUES(?,?,?,?,3,3,1,?,1,0,0,?)""",
                (host_id, "Jaipur", "Training District", "Demo Lane, Training District",
                 "Sample host stay for local demonstration only.", now),
            )
            accommodation_id = accommodation_cursor.lastrowid
            db.execute(
                """INSERT INTO services(
                       ngo_id,name,category,city,opening_hours,contact,address,
                       verified,blocked,closed,updated_at
                   ) VALUES(?,?,?,?,?,?,?,1,0,0,?)""",
                (ngo_id, "Demo Community Meal", "Food", "Jaipur", "12:00-14:00",
                 None, "Training District", now),
            )
            db.execute(
                """INSERT INTO alerts(
                       ngo_id,title,message,type,expires_at,blocked,archived,updated_at,created_at
                   ) VALUES(?,?,?,?,NULL,0,0,?,?)""",
                (ngo_id, "Sample community update",
                 "This is demonstration content, not a live service update.",
                 "Food", now, now),
            )

            for request_type, listing_id, status, message in (
                ("shelter", shelter_id, "Pending", "Sample request for NGO acceptance."),
                ("shelter", shelter_id, "Completed", "Sample completed stay for rating."),
            ):
                db.execute(
                    """INSERT INTO help_requests(
                           requester_id,handler_id,shelter_id,type,message,status,
                           updated_at,created_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        resident_id,
                        ngo_id if status == "Completed" else None,
                        listing_id,
                        request_type,
                        message,
                        status,
                        now,
                        now,
                    ),
                )
            db.execute(
                """INSERT INTO help_requests(
                       requester_id,accommodation_id,type,message,status,updated_at,created_at
                   ) VALUES(?,?, 'accommodation',?,'Pending',?,?)""",
                (resident_id, accommodation_id, "Sample request for host acceptance.", now, now),
            )
            db.execute(
                """INSERT INTO help_requests(
                       type,message,requester_name,contact,location_text,status,is_sos,
                       updated_at,created_at
                   ) VALUES('SOS',?,?,?,?, 'Pending',1,?,?)""",
                (
                    "Sample SOS for local demonstration only.",
                    "Demo Caller",
                    "000-000-0000",
                    "Training District, Jaipur",
                    now,
                    now,
                ),
            )
            db.execute(
                """INSERT INTO reports(
                       reporter_id,listing_type,listing_id,reason,status,updated_at,created_at
                   ) VALUES(?,?,?,'Sample report for admin review.','Open',?,?)""",
                (resident_id, "shelter", shelter_id, now, now),
            )
            db.execute(
                """INSERT INTO audit_log(actor_id,action,target_type,target_id,detail,created_at)
                   VALUES(?, 'demo_data_seeded', 'system', NULL, ?, ?)""",
                (admin_id, "Local demonstration records created.", now),
            )
            db.execute("INSERT INTO demo_seed(id,seeded_at) VALUES(1,?)", (now,))
            db.commit()
        finally:
            if db.in_transaction:
                db.rollback()

    print("Sample accounts (use the same temporary password for each):")
    for name, email, role, _gender, _verified in DEMO_USERS:
        print(f"  {role}: {name} - {email}")
    print(f"Temporary demo password: {password}")
    print("Sample records are fictional and for local demonstration only.")


if __name__ == "__main__":
    seed_demo_data()
