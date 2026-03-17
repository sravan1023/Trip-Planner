import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

def create_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS Destinations (
        destination_id INTEGER PRIMARY KEY,
        city TEXT NOT NULL,
        country TEXT NOT NULL,
        travel_type TEXT,
        avg_daily_cost REAL,
        best_season TEXT,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS Hotels (
        hotel_id INTEGER PRIMARY KEY,
        destination_id INTEGER NOT NULL,
        hotel_name TEXT NOT NULL,
        price_per_night REAL NOT NULL,
        rating REAL,
        amenities TEXT,
        hotel_type TEXT,
        FOREIGN KEY (destination_id) REFERENCES Destinations(destination_id)
    );

    CREATE TABLE IF NOT EXISTS Flights (
        flight_id INTEGER PRIMARY KEY,
        source_city TEXT NOT NULL,
        destination_id INTEGER NOT NULL,
        airline TEXT,
        departure_date TEXT,
        return_date TEXT,
        duration_hours REAL,
        avg_price REAL NOT NULL,
        stops INTEGER,
        FOREIGN KEY (destination_id) REFERENCES Destinations(destination_id)
    );

    CREATE TABLE IF NOT EXISTS Attractions (
        attraction_id INTEGER PRIMARY KEY,
        destination_id INTEGER NOT NULL,
        attraction_name TEXT NOT NULL,
        category TEXT,
        entry_fee REAL,
        recommended_duration_hours REAL,
        description TEXT,
        FOREIGN KEY (destination_id) REFERENCES Destinations(destination_id)
    );
    """)

    # Destinations 
    destinations = [
        (1, "Bali",          "Indonesia",    "beach",     80.0,  "April-October",   "Tropical island famous for temples, rice terraces, and surf beaches."),
        (2, "Paris",         "France",       "cultural",  200.0, "April-June",      "The City of Light, home to the Eiffel Tower, world-class cuisine, and art."),
        (3, "Queenstown",    "New Zealand",  "adventure", 150.0, "December-February","Adventure capital of the world nestled beside Lake Wakatipu."),
        (4, "Tokyo",         "Japan",        "city",      130.0, "March-May",       "Ultra-modern metropolis blending ancient temples with futuristic technology."),
        (5, "Cape Town",     "South Africa", "nature",    100.0, "November-March",  "Stunning coastal city framed by Table Mountain and diverse wildlife."),
        (6, "Santorini",     "Greece",       "beach",     180.0, "June-September",  "Iconic white-washed villages perched above the deep-blue Aegean Sea."),
        (7, "Machu Picchu",  "Peru",         "cultural",  90.0,  "May-September",   "Ancient Incan citadel set high in the Andes Mountains."),
        (8, "Reykjavik",     "Iceland",      "adventure", 160.0, "June-August",     "Gateway to the Northern Lights, geysers, and volcanic landscapes."),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO Destinations VALUES (?,?,?,?,?,?,?)", destinations
    )

    # Hotels 
    hotels = [

        (1,  1, "The Layar Villas",       350.0, 4.8, "wifi,pool,breakfast,spa",        "luxury"),
        (2,  1, "Kuta Beach Hotel",        60.0, 3.9, "wifi,breakfast",                 "budget"),
        (3,  1, "Seminyak Garden Resort", 130.0, 4.3, "wifi,pool,breakfast",            "standard"),
        (4,  2, "Hotel Ritz Paris",       900.0, 4.9, "wifi,spa,restaurant,concierge",  "luxury"),
        (5,  2, "Generator Paris",         45.0, 3.7, "wifi,bar",                       "budget"),
        (6,  2, "Hotel Lutetia",          400.0, 4.6, "wifi,pool,spa,restaurant",       "luxury"),
        (7,  3, "Eichardt's Private Hotel",380.0, 4.8, "wifi,breakfast,fireplace",      "luxury"),
        (8,  3, "Nomads Queenstown",        35.0, 3.8, "wifi,bar,kitchen",              "budget"),
        (9,  3, "Mercure Queenstown",      140.0, 4.2, "wifi,pool,restaurant",          "standard"),
        (10, 4, "Park Hyatt Tokyo",        550.0, 4.9, "wifi,pool,spa,restaurant",      "luxury"),
        (11, 4, "Khaosan Tokyo Kabuki",     30.0, 3.9, "wifi,breakfast",                "budget"),
        (12, 4, "Shinjuku Granbell Hotel", 160.0, 4.4, "wifi,bar,restaurant",           "standard"),
        (13, 5, "One&Only Cape Town",      500.0, 4.8, "wifi,pool,spa,restaurant",      "luxury"),
        (14, 5, "Once in Cape Town",        55.0, 4.0, "wifi,kitchen",                  "budget"),
        (15, 5, "The Portswood Hotel",     180.0, 4.3, "wifi,pool,restaurant",          "standard"),
        (16, 6, "Grace Hotel Santorini",   600.0, 4.9, "wifi,pool,spa,breakfast",       "luxury"),
        (17, 6, "Caveland Hostel",          40.0, 4.1, "wifi,breakfast",                "budget"),
        (18, 6, "Astra Suites",            280.0, 4.6, "wifi,pool,breakfast",           "standard"),
        (19, 7, "Belmond Sanctuary Lodge", 900.0, 4.9, "wifi,restaurant,spa",           "luxury"),
        (20, 7, "Hostel Inti Wasi",         25.0, 3.8, "wifi,kitchen",                  "budget"),
        (21, 7, "Sumaq Machu Picchu",      320.0, 4.7, "wifi,spa,restaurant",           "standard"),
        (22, 8, "101 Hotel",               350.0, 4.7, "wifi,spa,restaurant",           "luxury"),
        (23, 8, "Kex Hostel",               55.0, 4.2, "wifi,bar,kitchen",              "budget"),
        (24, 8, "Centerhotel Arnarhvoll",  200.0, 4.4, "wifi,restaurant,bar",           "standard"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO Hotels VALUES (?,?,?,?,?,?,?)", hotels
    )

    # Flights 
    flights = [
        (1,  "New York",      1, "Singapore Airlines", "2026-06-01", "2026-06-15", 21.0,  950.0,  1),
        (2,  "London",        1, "Emirates",           "2026-06-05", "2026-06-20", 16.5, 1100.0,  1),
        (3,  "Sydney",        1, "Garuda Indonesia",   "2026-07-10", "2026-07-24",  6.0,  280.0,  0),
        (4,  "New York",      2, "Air France",         "2026-05-15", "2026-05-25",  7.5,  650.0,  0),
        (5,  "Bangalore",     2, "Lufthansa",          "2026-08-01", "2026-08-10",  9.5,  820.0,  1),
        (6,  "Dubai",         2, "Emirates",           "2026-09-10", "2026-09-20",  7.0,  600.0,  0),
        (7,  "Sydney",        3, "Qantas",             "2026-12-20", "2027-01-03",  3.0,  320.0,  0),
        (8,  "Los Angeles",   3, "Air New Zealand",    "2026-12-22", "2027-01-05", 12.5,  980.0,  1),
        (9,  "New York",      4, "Japan Airlines",     "2026-03-25", "2026-04-04", 14.0,  870.0,  0),
        (10, "London",        4, "British Airways",    "2026-04-01", "2026-04-12", 12.0,  950.0,  1),
        (11, "Delhi",         4, "ANA",                "2026-03-30", "2026-04-09",  8.5,  540.0,  0),
        (12, "London",        5, "British Airways",    "2026-11-15", "2026-11-28", 11.5,  780.0,  0),
        (13, "New York",      5, "South African Airways","2026-12-01","2026-12-15", 15.0,  920.0,  1),
        (14, "London",        6, "easyJet",            "2026-07-01", "2026-07-10",  3.5,  250.0,  0),
        (15, "New York",      6, "Delta",              "2026-07-05", "2026-07-15",  9.0,  780.0,  1),
        (16, "Miami",         7, "LATAM Airlines",     "2026-05-20", "2026-05-30",  5.0,  480.0,  1),
        (17, "London",        7, "Iberia",             "2026-06-10", "2026-06-22", 13.0,  860.0,  1),
        (18, "New York",      8, "Icelandair",         "2026-06-15", "2026-06-25",  6.5,  520.0,  0),
        (19, "London",        8, "easyJet",            "2026-07-01", "2026-07-10",  2.5,  180.0,  0),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO Flights VALUES (?,?,?,?,?,?,?,?,?)", flights
    )

    # Attractions 
    attractions = [
        (1,  1, "Tanah Lot Temple",      "landmark",  5.0,  2.0, "Iconic sea temple perched on a rocky outcrop."),
        (2,  1, "Ubud Monkey Forest",    "nature",    5.0,  2.0, "Sacred forest sanctuary home to hundreds of Balinese macaques."),
        (3,  1, "Seminyak Beach",        "beach",     0.0,  3.0, "Trendy beach with luxury beach clubs and stunning sunsets."),
        (4,  1, "Tegallalang Rice Terrace","nature",  2.0,  1.5, "Breathtaking UNESCO-listed stepped rice paddies."),
        (5,  2, "Eiffel Tower",          "landmark", 28.0,  2.0, "The iconic iron lattice tower on the Champ de Mars."),
        (6,  2, "Louvre Museum",         "museum",   17.0,  4.0, "World's largest art museum housing the Mona Lisa."),
        (7,  2, "Notre-Dame Cathedral",  "landmark",  0.0,  1.5, "Medieval Catholic cathedral on the Île de la Cité."),
        (8,  2, "Musée d'Orsay",         "museum",   16.0,  3.0, "Impressionist art museum housed in a Beaux-Arts railway station."),
        (9,  3, "Bungee Jumping - Kawarau Bridge","hiking", 195.0, 2.0, "World's first commercial bungee jump site."),
        (10, 3, "Milford Sound Cruise",  "nature",   85.0,  8.0, "Fiord cruise through towering peaks and waterfalls."),
        (11, 3, "Skyline Gondola",       "landmark", 32.0,  2.0, "Scenic gondola ride with panoramic lake views."),
        (12, 4, "Senso-ji Temple",       "landmark",  0.0,  1.5, "Ancient Buddhist temple in the Asakusa district."),
        (13, 4, "Shibuya Crossing",      "landmark",  0.0,  0.5, "World's busiest pedestrian crossing."),
        (14, 4, "teamLab Borderless",    "museum",   32.0,  3.0, "Immersive digital art museum."),
        (15, 4, "Shinjuku Gyoen",        "nature",    5.0,  2.0, "Expansive national garden famed for cherry blossoms."),
        (16, 5, "Table Mountain",        "nature",   22.0,  3.0, "Iconic flat-topped mountain with cable car access."),
        (17, 5, "Robben Island",         "museum",   30.0,  4.0, "UNESCO World Heritage Site where Mandela was imprisoned."),
        (18, 5, "Boulders Beach Penguins","beach",   11.0,  1.5, "Beach colony of endangered African penguins."),
        (19, 6, "Oia Sunset Viewpoint",  "landmark",  0.0,  1.5, "The most famous sunset in the world."),
        (20, 6, "Akrotiri Archaeological Site","museum",14.0, 2.0, "Minoan Bronze Age settlement preserved by volcanic ash."),
        (21, 6, "Red Beach",             "beach",     0.0,  2.0, "Dramatic beach of deep-red volcanic cliffs."),
        (22, 7, "Machu Picchu Citadel",  "landmark", 45.0,  5.0, "15th-century Inca citadel set amidst the Andes."),
        (23, 7, "Sun Gate (Inti Punku)", "hiking",    0.0,  3.0, "Ancient gateway on the Inca Trail with panoramic views."),
        (24, 7, "Huayna Picchu",         "hiking",   15.0,  3.0, "Steep mountain peak with aerial views of the ruins."),
        (25, 8, "Northern Lights Tour",  "nature",   80.0,  4.0, "Guided tour to witness the Aurora Borealis."),
        (26, 8, "Blue Lagoon",           "nature",   60.0,  3.0, "Famous geothermal spa surrounded by lava fields."),
        (27, 8, "Hallgrímskirkja Church","landmark",  0.0,  1.0, "Striking modernist Lutheran church and city icon."),
        (28, 8, "Golden Circle Tour",    "nature",   90.0,  8.0, "Route covering Þingvellir, Geysir, and Gullfoss waterfall."),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO Attractions VALUES (?,?,?,?,?,?,?)", attractions
    )

    conn.commit()
    conn.close()
    print(f"Database created successfully at: {DB_PATH}")
    print("Tables: Destinations, Hotels, Flights, Attractions")
    print(f"  Destinations : {len(destinations)} rows")
    print(f"  Hotels       : {len(hotels)} rows")
    print(f"  Flights      : {len(flights)} rows")
    print(f"  Attractions  : {len(attractions)} rows")

if __name__ == "__main__":
    create_db()
