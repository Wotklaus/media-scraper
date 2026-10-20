
const API_URL = "";

const form = document.getElementById("searchForm");
const searchButton = document.getElementById("searchButton");
const statusMessage = document.getElementById("statusMessage");
const dashboard = document.getElementById("dashboard");
const avatar = document.getElementById("profileAvatar");
const avatarFallback = document.getElementById("avatarFallback");

const detailsModal = document.getElementById("detailsModal");
const detailsTitle = document.getElementById("detailsTitle");
const detailsContent = document.getElementById("detailsContent");

const videosGrid = document.getElementById("videosGrid");
const videosMessage = document.getElementById("videosMessage");
const videosCount = document.querySelector(".videos-card .tag");

let currentVideos = [];
let currentVideoIndex = 0;

// Update text safely.
function setText(id, value) {
    document.getElementById(id).textContent =
        value ?? "No disponible";
}

// Display the profile avatar.
function showAvatar(profile) {
    avatar.style.display = "none";
    avatar.removeAttribute("src");
    avatarFallback.style.display = "block";

    avatarFallback.textContent =
        (profile.nickname || profile.username || "?")
            .charAt(0)
            .toUpperCase();

    if (profile.avatar_url) {
        avatar.onload = () => {
            avatar.style.display = "block";
            avatarFallback.style.display = "none";
        };

        avatar.onerror = () => {
            avatar.style.display = "none";
            avatarFallback.style.display = "block";
        };

        avatar.src = profile.avatar_url;
    }
}

// Create a video metric.
function createMetricChip(label, value) {
    const chip = document.createElement("div");
    chip.className = "metric-chip";

    const name = document.createElement("span");
    name.textContent = label;

    const metric = document.createElement("strong");
    metric.textContent = value ?? "N/A";

    chip.append(name, metric);

    return chip;
}

// Create a single video card.
function createVideoCard(video) {
    const card = document.createElement("article");
    card.className = "video-card";

    const link = document.createElement("a");
    link.className = "video-thumbnail";
    link.target = "_blank";
    link.rel = "noopener noreferrer";

    if (video.url && /^https:\/\/www\.tiktok\.com\//.test(video.url)) {
        link.href = video.url;
    } else {
        link.removeAttribute("href");
    }

    if (video.preview_url) {
        const image = document.createElement("img");
        image.src = video.preview_url;
        image.alt = video.title || "Vista previa del video";
        image.loading = "lazy";
        link.appendChild(image);
    } else {
        const placeholder = document.createElement("div");
        placeholder.className = "video-placeholder";
        placeholder.textContent = "Vista previa no disponible";
        link.appendChild(placeholder);
    }

    const body = document.createElement("div");
    body.className = "video-body";

    const title = document.createElement("p");
    title.className = "video-title";
    title.textContent = video.title || "Sin descripción";

    const metrics = document.createElement("div");
    metrics.className = "video-metrics";

    metrics.append(
        createMetricChip("Visualizaciones", video.views),
        createMetricChip("Me gusta", video.likes),
        createMetricChip("Comentarios", video.comments),
        createMetricChip("Compartidos", video.shares),
        createMetricChip("Guardados", video.saves)
    );

    body.append(title, metrics);
    card.append(link, body);

    return card;
}

// Render one video and its navigation controls.
function renderCurrentVideo() {
    videosGrid.replaceChildren();

    if (currentVideos.length === 0) {
        videosCount.textContent = "0 / 10";
        videosMessage.textContent =
            "No se pudieron obtener publicaciones.";
        videosMessage.classList.remove("hidden");
        return;
    }

    videosMessage.classList.add("hidden");

    const video = currentVideos[currentVideoIndex];
    videosGrid.appendChild(createVideoCard(video));

    videosCount.textContent =
        `${currentVideoIndex + 1} / ${currentVideos.length}`;

    const navigation = document.createElement("div");
    navigation.className = "video-pagination";

    const previous = document.createElement("button");
    previous.className = "pagination-button";
    previous.textContent = "← Anterior";
    previous.disabled = currentVideoIndex === 0;

    const label = document.createElement("span");
    label.className = "pagination-label";
    label.textContent =
        `Video ${currentVideoIndex + 1} de ${currentVideos.length}`;

    const next = document.createElement("button");
    next.className = "pagination-button";
    next.textContent = "Siguiente →";
    next.disabled =
        currentVideoIndex === currentVideos.length - 1;

    previous.addEventListener("click", () => {
        if (currentVideoIndex > 0) {
            currentVideoIndex--;
            renderCurrentVideo();
        }
    });

    next.addEventListener("click", () => {
        if (currentVideoIndex < currentVideos.length - 1) {
            currentVideoIndex++;
            renderCurrentVideo();
        }
    });

    navigation.append(previous, label, next);
    videosGrid.appendChild(navigation);
}

// Store videos and reset pagination.
function displayVideos(videos) {
    currentVideos = Array.isArray(videos) ? videos.slice(0, 10) : [];
    currentVideoIndex = 0;
    renderCurrentVideo();
}

// Display profile details.
function displayProfile(profile) {
    setText("profileName", profile.nickname);
    setText("profileUsername", `@${profile.username}`);
    setText("profileBio", profile.bio);

    setText("followers", profile.followers);
    setText("following", profile.following);
    setText("likes", profile.likes);

    showAvatar(profile);

    const profileLink = document.getElementById("profileLink");
    profileLink.href =
        `https://www.tiktok.com/@${encodeURIComponent(profile.username)}`;

    displayVideos(profile.videos);
    dashboard.classList.remove("hidden");
}

// Request data from FastAPI.
async function fetchProfile(username) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);

    try {
        const response = await fetch(
            `${API_URL}/api/profile/${encodeURIComponent(username)}`,
            { signal: controller.signal }
        );

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(
                typeof error.detail === "string"
                    ? error.detail
                    : "No se pudo consultar el perfil."
            );
        }

        return await response.json();

    } finally {
        clearTimeout(timeout);
    }
}

// Handle profile searches.
form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const username = document.getElementById("username")
        .value.trim().replace(/^@/, "");

    if (!username) {
        statusMessage.textContent = "Ingresa un username.";
        return;
    }

    searchButton.disabled = true;
    dashboard.classList.add("hidden");
    statusMessage.textContent = "Consultando perfil y publicaciones...";

    try {
        const profile = await fetchProfile(username);
        displayProfile(profile);
        statusMessage.textContent = "Consulta completada.";

    } catch (error) {
        statusMessage.textContent =
            error.name === "AbortError"
                ? "La consulta excedió los 120 segundos."
                : error.message;

    } finally {
        searchButton.disabled = false;
    }
});

// Show statistic details.
document.querySelectorAll(".stat-item").forEach((button) => {
    button.addEventListener("click", () => {
        const field = button.dataset.field;

        const labels = {
            followers: "Seguidores",
            following: "Seguidos",
            likes: "Me gusta"
        };

        detailsTitle.textContent = labels[field];
        detailsContent.textContent =
            `Valor actual: ${document.getElementById(field).textContent}. ` +
            "El análisis detallado estará disponible próximamente.";

        detailsModal.showModal();
    });
});

// Close the details window.
document.getElementById("closeDetails")
    .addEventListener("click", () => detailsModal.close());
