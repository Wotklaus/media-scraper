
const API_URL = "";

const form = document.getElementById("searchForm");
const searchButton = document.getElementById("searchButton");
const statusMessage = document.getElementById("statusMessage");
const dashboard = document.getElementById("dashboard");
const avatar = document.getElementById("profileAvatar");
const avatarFallback = document.getElementById("avatarFallback");

const videosGrid = document.getElementById("videosGrid");
const videosMessage = document.getElementById("videosMessage");
const videosCount = document.querySelector(".videos-card .tag");

const downloadJSON = document.getElementById("downloadJSON");
const downloadCSV = document.getElementById("downloadCSV");

let currentProfile = null;
let currentVideos = [];


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
        image.addEventListener("error", () => {
            const placeholder = document.createElement("div");
            placeholder.className = "video-placeholder";
            placeholder.textContent = "Vista previa no disponible";
            link.replaceChildren(placeholder);
        });
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
        createMetricChip("👁️ Visualizaciones", video.views),
        createMetricChip("❤️ Me gusta", video.likes),
        createMetricChip("💬 Comentarios", video.comments),
        createMetricChip("🔁 Compartidos", video.shares),
        createMetricChip("🔖 Guardados", video.saves)
    );

    const original = document.createElement("a");
    original.className = "original-link";
    original.textContent = "Abrir publicación ↗";
    if (link.hasAttribute("href")) {
        original.href = link.href;
        original.target = "_blank";
        original.rel = "noopener noreferrer";
    } else {
        original.textContent = "Enlace no disponible";
    }
    title.title = title.textContent;
    body.append(title, metrics, original);
    card.append(link, body);

    return card;
}

// Keep every publication returned by the backend, in its original order.
function displayVideos(videos) {
    currentVideos = Array.isArray(videos) ? videos : [];
    videosGrid.replaceChildren(...currentVideos.map(createVideoCard));
    videosCount.textContent = `${currentVideos.length} publicaciones`;
    videosMessage.textContent = "No se pudieron obtener publicaciones.";
    videosMessage.classList.toggle("hidden", currentVideos.length > 0);
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
    renderStatistics();
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
    currentVideos = [];
    renderStatistics();
    downloadJSON.disabled = true;
    downloadCSV.disabled = true;
    dashboard.classList.add("hidden");
    statusMessage.textContent = "Consultando TikTok. Puede tardar varios minutos...";

    try {
        const profile = await fetchProfile(username);
        displayProfile(profile);
        const count = currentVideos.length;
        statusMessage.textContent = count < 10
            ? `Se recuperaron ${count} publicaciones de hasta 10 solicitadas.`
            : profile._meta?.warnings?.length
                ? "Consulta completada con datos parciales. Algunas métricas o comentarios pueden no estar disponibles."
                : "";

    } catch (error) {
        statusMessage.textContent =
            error.name === "AbortError"
                ? "La consulta excedió los 10 minutos. El proceso puede seguir terminando; espera antes de reintentar."
                : error.message;

    } finally {
        searchButton.disabled = false;
    }
});

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

// General keeps its result; Big Five reads stored data independently.
let activeSection = 'general';
document.querySelectorAll('[data-section]').forEach((button) => {
    button.addEventListener('click', () => {
        if (button.dataset.section === 'big-five' && window.bigFive) {
            window.bigFive.open(activeSection === 'general' ? currentProfile?.username : null);
        }
        activeSection = button.dataset.section;
        document.querySelectorAll('.app-section').forEach((section) => {
            const active = section.id === button.dataset.section;
            section.hidden = !active;
            section.classList.toggle('hidden', !active);
        });
        document.querySelectorAll('[data-section]').forEach((item) => {
            if (item === button) item.setAttribute('aria-current', 'page');
            else item.removeAttribute('aria-current');
        });
    });
});

// Accept unambiguous counts only. Never interpret missing values as zero.
function metricNumber(value) {
    if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? value : null;
    if (typeof value !== 'string') return null;
    const text = value.trim();
    if (/^\d+$/.test(text)) return Number.isFinite(Number(text)) ? Number(text) : null;
    const match = text.match(/^(\d+(?:[.,]\d+)?)\s*([KMB])$/i);
    if (!match) return null;
    const number = Number(match[1].replace(',', '.')) * ({k: 1e3, m: 1e6, b: 1e9}[match[2].toLowerCase()]);
    return Number.isFinite(number) ? number : null;
}

function interactionCount(video) {
    const counts = ['likes', 'comments', 'shares', 'saves'].map((field) => metricNumber(video[field]));
    return counts.every((count) => count !== null) ? counts.reduce((sum, count) => sum + count, 0) : null;
}

const formatNumber = (value) => new Intl.NumberFormat('es-EC', {maximumFractionDigits: 1}).format(value);

function renderRanking() {
    const field = document.getElementById('rankingSort').value;
    const ranked = currentVideos.map((video) => ({video, value: field === 'views' ? metricNumber(video.views) : interactionCount(video)}))
        .filter((item) => item.value !== null).sort((a, b) => b.value - a.value).slice(0, 10);
    const list = document.getElementById('rankingList');
    list.replaceChildren();
    const maximum = Math.max(1, ...ranked.map((item) => item.value));
    ranked.forEach(({video, value}) => {
        const item = document.createElement('li');
        const label = document.createElement('span');
        label.textContent = video.title || 'Sin descripción';
        const amount = document.createElement('strong');
        amount.textContent = formatNumber(value);
        const bar = document.createElement('div');
        bar.className = 'ranking-bar';
        bar.style.width = `${value / maximum * 100}%`;
        item.append(label, amount, bar);
        list.appendChild(item);
    });
    const message = document.getElementById('rankingMessage');
    message.classList.toggle('hidden', ranked.length > 0);
    message.textContent = currentProfile ? 'No hay métricas suficientes para este orden. Las interacciones requieren las cuatro métricas.' : 'Analiza un perfil en General para ver sus publicaciones.';
}

function renderStatistics() {
    document.getElementById('statisticsContext').textContent = currentProfile
        ? `@${currentProfile.username} · ${currentVideos.length} publicaciones recuperadas`
        : 'Analiza un perfil en General para explorar sus datos.';
    const summary = document.getElementById('interactionSummary');
    summary.replaceChildren();
    const views = currentVideos.map((video) => metricNumber(video.views)).filter((value) => value !== null);
    const interactions = currentVideos.map(interactionCount).filter((value) => value !== null);
    const paired = currentVideos.map((video) => ({views: metricNumber(video.views), interactions: interactionCount(video)}))
        .filter((item) => item.views !== null && item.views > 0 && item.interactions !== null);
    const rate = paired.length ? paired.reduce((sum, item) => sum + item.interactions, 0) / paired.reduce((sum, item) => sum + item.views, 0) * 100 : null;
    [
        ['👁️ Promedio de visualizaciones', views.length ? formatNumber(views.reduce((sum, value) => sum + value, 0) / views.length) : 'No disponible', `${views.length} publicaciones con visualizaciones`],
        ['❤️ Total de interacciones', interactions.length ? formatNumber(interactions.reduce((sum, value) => sum + value, 0)) : 'No disponible', `${interactions.length} publicaciones con las cuatro métricas`],
        ['📊 Tasa de interacción', rate !== null ? `${formatNumber(rate)} %` : 'No disponible', `${paired.length} publicaciones con datos completos y visualizaciones > 0`],
    ].forEach(([label, value, coverage]) => {
        const card = createMetricChip(label, value);
        const note = document.createElement('small');
        note.textContent = coverage;
        card.appendChild(note);
        summary.appendChild(card);
    });
    renderRanking();
    const hashtags = new Map();
    currentVideos.forEach((video) => {
        const tags = String(video.title || '').match(/#[\p{L}\p{N}_]+/gu) || [];
        tags.forEach((tag) => { const key = tag.toLocaleLowerCase('es'); hashtags.set(key, (hashtags.get(key) || 0) + 1); });
    });
    const hashtagList = document.getElementById('hashtagList');
    hashtagList.replaceChildren();
    [...hashtags].sort((a, b) => b[1] - a[1]).slice(0, 10).forEach(([tag, count]) => {
        const item = document.createElement('span');
        item.className = 'tag';
        item.textContent = `${tag} · ${count}`;
        hashtagList.appendChild(item);
    });
    document.getElementById('hashtagMessage').classList.toggle('hidden', hashtags.size > 0);
}

document.getElementById('rankingSort').addEventListener('change', renderRanking);
renderStatistics();
