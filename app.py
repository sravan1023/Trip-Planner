import streamlit as st

from agent.pipeline import run_agent
from agent.tools import get_weather
from config import GROQ_API_KEY, MODELS
from rag.ingest import run_full_ingest
from rag.vector_store import collection_count
from ui.markup import (
    error_html,
    hero_html,
    section_label_html,
    sidebar_footer_html,
    sidebar_header_html,
    source_chunk_html,
    source_expander_label,
    spacer_html,
    weather_card_html,
)
from ui.styles import APP_CSS


st.set_page_config(page_title="TripPlanner VA", page_icon="✈️", layout="wide")
st.markdown(APP_CSS, unsafe_allow_html=True)


if not GROQ_API_KEY:
    st.error("Missing GROQ_API_KEY. Add it in Streamlit secrets or as an environment variable before deploying the app.")
    st.info("Optional configuration values: HF_TOKEN and CHROMA_DB_PATH.")
    st.stop()


@st.cache_resource(show_spinner="Indexing travel knowledge base (one-time, ~30s)...")
def _ensure_indexed() -> int:
    """Run ingest once if the Chroma collection is empty. Cached for the
    Streamlit session so it doesn't re-check on every rerun."""
    if collection_count() == 0:
        result = run_full_ingest()
        return result.get("total", 0)
    return collection_count()


_ensure_indexed()


EXAMPLES = [
    (
        "California coast",
        "Santa Cruz, Monterey and Big Sur",
        "Compare Santa Cruz, Monterey, and Big Sur for a weekend getaway",
    ),
    (
        "Park comparison",
        "Yosemite, Sequoia and Joshua Tree",
        "Compare Yosemite, Sequoia, and Joshua Tree for hiking, scenery, and trip style",
    ),
    (
        "Bay Area food",
        "Neighborhoods and local favorites",
        "What are the best food neighborhoods and places to eat in San Francisco?",
    ),
    (
        "Road trip planner",
        "Pacific Coast Highway and scenic stops",
        "Plan a Pacific Coast Highway road trip with scenic stops and places to stay",
    ),
]

MODE_LABELS = {
    "Fast": "8B",
    "Thinking": "70B",
}

LEGACY_MODE_ALIASES = {
    "Quick": "Fast",
    "Deep Plan": "Thinking",
    "8B": "Fast",
    "70B": "Thinking",
}


def render_html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def render_source_chunks(chunks) -> None:
    with st.expander(source_expander_label(len(chunks)), expanded=False):
        for index, chunk in enumerate(chunks, 1):
            render_html(source_chunk_html(chunk, index=index))


if "messages" not in st.session_state:
    st.session_state.messages = []
if "model_mode" not in st.session_state:
    st.session_state.model_mode = "Fast"
if "weather_data" not in st.session_state:
    st.session_state.weather_data = None

st.session_state.model_mode = LEGACY_MODE_ALIASES.get(
    st.session_state.model_mode,
    st.session_state.model_mode,
)
if st.session_state.model_mode not in MODE_LABELS:
    st.session_state.model_mode = "Fast"


with st.sidebar:
    render_html(sidebar_header_html())
    render_html(section_label_html("Response Mode", color="#6E6E73", margin_bottom=10, font_size=11))

    st.session_state.model_mode = st.radio(
        "mode",
        options=list(MODE_LABELS),
        index=list(MODE_LABELS).index(st.session_state.model_mode),
        horizontal=True,
        label_visibility="collapsed",
        format_func=MODE_LABELS.get,
    )

    render_html(spacer_html(14))

    render_html(section_label_html("Tools", color="#6E6E73", margin_bottom=10, font_size=11))

    with st.expander("Weather", expanded=False):
        city_input = st.text_input("City", placeholder="e.g. Tokyo", key="wcity")
        if st.button("Check Weather", use_container_width=True):
            if city_input.strip():
                st.session_state.weather_data = get_weather(city_input.strip())

        if st.session_state.weather_data:
            weather = st.session_state.weather_data
            if "error" in weather:
                render_html(error_html(f'Could not fetch: {weather["error"]}'))
            else:
                render_html(weather_card_html(weather))

    if st.session_state.messages:
        render_html(spacer_html(12))
        if st.button("Clear Conversation", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

    render_html(sidebar_footer_html())


if not st.session_state.messages:
    render_html(hero_html())
    render_html(section_label_html("Try one of these", color="#555", margin_bottom=12, font_size=11))

    with st.container(key="example-grid"):
        columns = st.columns(2, gap="small")
        for index, (title, subtitle, query) in enumerate(EXAMPLES):
            with columns[index % 2]:
                label = f"{title}\n{subtitle}"
                if st.button(label, key=f"ex_{index}", use_container_width=True):
                    st.session_state.messages.append(
                        {"role": "user", "content": query, "rag_chunks": []}
                    )
                    st.rerun()

else:
    with st.container(key="chat-header"):
        back_col, title_col, mode_col = st.columns([1, 6, 2])
        with back_col:
            if st.button("← Back", key="back-home"):
                st.session_state.messages = []
                st.rerun()
        with title_col:
            st.markdown("<span style='font-size:16px;font-weight:700;line-height:2.2'>TripPlanner AI</span>", unsafe_allow_html=True)
        with mode_col:
            st.markdown(
                f"<div style='text-align:right;padding-top:6px'>"
                f"<span style='font-size:11.5px;color:#bbb;background:#131313;border:1px solid #262626;border-radius:20px;padding:4px 12px'>{MODE_LABELS[st.session_state.model_mode]}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    st.divider()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("rag_chunks"):
                render_source_chunks(message["rag_chunks"])

    # Handle example-button queries: last message is user with no assistant reply yet
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        pending = st.session_state.messages[-1]["content"]
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]
        model_id = MODELS[st.session_state.model_mode]
        with st.chat_message("assistant"):
            with st.spinner(""):
                try:
                    response_text, rag_chunks = run_agent(pending, model_id, history=history, stream=False)
                except Exception as exc:
                    response_text = f"Something went wrong: {exc}"
                    rag_chunks = []
            st.markdown(response_text)
            if rag_chunks:
                render_source_chunks(rag_chunks)
        st.session_state.messages.append(
            {"role": "assistant", "content": response_text, "rag_chunks": rag_chunks}
        )
        st.rerun()


if prompt := st.chat_input("Ask me about destinations, hotels, flights, visas..."):
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]
    st.session_state.messages.append({"role": "user", "content": prompt, "rag_chunks": []})
    with st.chat_message("user"):
        st.markdown(prompt)

    model_id = MODELS[st.session_state.model_mode]

    with st.chat_message("assistant"):
        with st.spinner(""):
            try:
                response_text, rag_chunks = run_agent(prompt, model_id, history=history, stream=False)
            except Exception as exc:
                response_text = f"Something went wrong: {exc}"
                rag_chunks = []

        st.markdown(response_text)
        if rag_chunks:
            render_source_chunks(rag_chunks)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response_text,
            "rag_chunks": rag_chunks,
        }
    )