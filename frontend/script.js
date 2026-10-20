
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

const downloadJSON = document.getElementById("downloadJSON");
const downloadCSV = document.getElementById("downloadCSV");

let currentProfile = null;
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
    currentProfile = profile;
    downloadJSON.disabled = false;
    downloadCSV.disabled = false;
    dashboard.classList.remove("hidden");
}

// Request data from FastAPI.
async function fetchProfile(username) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 600000);

    try {
        const response = await fetch(
            `${API_URL}/api/profile/${encodeURIComponent(username)}?mode=real`,
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
    currentProfile = null;
    downloadJSON.disabled = true;
    downloadCSV.disabled = true;
    dashboard.classList.add("hidden");
    statusMessage.textContent = "Consultando TikTok. Puede tardar varios minutos...";

    try {
        const profile = await fetchProfile(username);
        displayProfile(profile);
        statusMessage.textContent = (profile._meta?.warnings || []).join(" ");

    } catch (error) {
        statusMessage.textContent =
            error.name === "AbortError"
                ? "La consulta excedió los 10 minutos. El proceso puede seguir terminando; espera antes de reintentar."
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

// Project only the public fields, without changing the displayed response.
function publicExport(profile) {
    const pick = (source, fields) => Object.fromEntries(fields.map((key) => [key, source[key] ?? null]));
    const result = pick(profile, ["username", "nickname", "bio", "avatar_url", "url", "followers", "following", "likes"]);
    for (const key of ["followers_users", "following_users"]) {
        if (key in profile) result[key] = profile[key].slice();
    }
    result.videos = (profile.videos || []).map((video) => {
        const item = pick(video, ["id", "url", "title", "preview_url", "views", "likes", "comments", "shares", "saves"]);
        if ("comments_list" in video) {
            item.comments_list = video.comments_list.map((comment) => pick(comment, ["username", "text"]));
        }
        return item;
    });
    if (profile._meta) {
        result._meta = {};
        for (const key of ["mode", "captured_at", "warnings"]) {
            if (key in profile._meta) result._meta[key] = profile._meta[key];
        }
    }
    return result;
}

function csvCell(value) {
    let text = value == null ? "null" : typeof value === "object" ? JSON.stringify(value) : String(value);
    if (/^[\s\u0000-\u001f]*[=+@-]/u.test(text) || /^[\t\r\n]/u.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
}

function exportCSV(profile) {
    const headers = ["Usuario", "Nickname", "URL del perfil", "Biografía", "Avatar URL", "Seguidores", "Seguidos", "Likes del perfil",
        "ID publicación", "URL publicación", "Descripción", "Miniatura URL", "Visualizaciones", "Likes publicación", "Comentarios", "Compartidos", "Guardados",
        "Comentarios recuperados", "Usuarios seguidores recuperados", "Usuarios seguidos recuperados", "Metadatos"];
    const posts = profile.videos.length ? profile.videos : [null];
    const rows = posts.map((post) => [profile.username, profile.nickname, profile.url, profile.bio, profile.avatar_url,
        profile.followers, profile.following, profile.likes, post?.id, post?.url, post?.title, post?.preview_url,
        post?.views, post?.likes, post?.comments, post?.shares, post?.saves, post?.comments_list,
        profile.followers_users, profile.following_users, profile._meta]);
    return "\uFEFF" + [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

function downloadResult(format) {
    if (!currentProfile) return;
    const profile = publicExport(currentProfile);
    const content = format === "json" ? JSON.stringify(profile, null, 2) : exportCSV(profile);
    const blob = new Blob([content], {type: format === "json" ? "application/json;charset=utf-8" : "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const username = String(profile.username || "perfil").replace(/[^a-zA-Z0-9._]/g, "_");
    link.href = url;
    link.download = `media-scraper_${username}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

downloadJSON.addEventListener("click", () => downloadResult("json"));
downloadCSV.addEventListener("click", () => downloadResult("csv"));
