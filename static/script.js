// script.js - Frontend logic for Website Change Detector

let websites = [];

document.addEventListener("DOMContentLoaded", loadWebsites);

// Fetch all monitored websites and update dashboard
async function loadWebsites() {
    try {
        const res = await fetch("/api/websites");
        const data = await res.json();
        if (data.success) {
            websites = data.websites;
            updateStats(data.stats);
            renderTable(websites);
        }
    } catch (err) {
        showToast("Error loading websites from server.");
    }
}

// Update stat counters
function updateStats(stats) {
    document.getElementById("stat-total").textContent = stats.total || 0;
    document.getElementById("stat-changed").textContent = stats.changed || 0;
    document.getElementById("stat-unchanged").textContent = stats.unchanged || 0;
    document.getElementById("stat-errors").textContent = stats.errors || 0;
}

// Render website rows into the table
function renderTable(list) {
    const tbody = document.getElementById("sites-tbody");
    const empty = document.getElementById("empty-state");
    tbody.innerHTML = "";

    if (list.length === 0) {
        empty.classList.remove("hidden");
        return;
    }
    empty.classList.add("hidden");

    list.forEach(site => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>
                <strong>${escapeHtml(site.name)}</strong>
                <a href="${escapeHtml(site.url)}" target="_blank" class="table-link">${escapeHtml(site.url)} ↗</a>
            </td>
            <td><span class="badge ${getBadgeClass(site.last_status)}">${site.last_status}</span></td>
            <td><small style="color:#94a3b8;">${escapeHtml(site.last_message || '')}</small></td>
            <td><small>${site.last_checked || 'Never'}</small></td>
            <td>
                <div class="actions">
                    <button class="btn btn-sm btn-outline" onclick="checkWebsite(${site.id})">🔄 Check</button>
                    <button class="btn btn-sm btn-outline" onclick="showHistory(${site.id})">📜 History</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteWebsite(${site.id}, '${escapeHtml(site.name)}')">🗑️</button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// Map status to badge CSS class
function getBadgeClass(status) {
    const map = {
        "Changed": "badge-changed",
        "No Change": "badge-no-change",
        "Baseline Created": "badge-baseline",
        "Error": "badge-error",
    };
    return map[status] || "badge-pending";
}

// Add a new website
async function handleAddWebsite(e) {
    e.preventDefault();
    const name = document.getElementById("site-name").value.trim();
    const url = document.getElementById("site-url").value.trim();
    const btn = document.getElementById("btn-submit");

    btn.disabled = true;
    btn.textContent = "Scanning...";

    try {
        const res = await fetch("/api/websites", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, url })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message);
            document.getElementById("add-form").reset();
            document.getElementById("add-card").classList.add("hidden");
            loadWebsites();
        } else {
            showToast(data.error || "Failed to add website.");
        }
    } catch (err) {
        showToast("Network error while adding website.");
    } finally {
        btn.disabled = false;
        btn.textContent = "Start Monitoring";
    }
}

// Check a single website for changes
async function checkWebsite(id) {
    showToast("Scanning website for changes...");
    try {
        const res = await fetch(`/api/websites/${id}/check`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast(`${data.status}: ${data.message}`);
            loadWebsites();
        } else {
            showToast(data.error || "Check failed.");
        }
    } catch (err) {
        showToast("Error checking website.");
    }
}

// Delete a website
async function deleteWebsite(id, name) {
    if (!confirm(`Stop monitoring "${name}"?`)) return;
    try {
        const res = await fetch(`/api/websites/${id}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast(data.message);
            loadWebsites();
        }
    } catch (err) {
        showToast("Failed to delete website.");
    }
}

// Show change history modal with diff highlighting
async function showHistory(id) {
    const modal = document.getElementById("history-modal");
    const body = document.getElementById("modal-body");
    body.innerHTML = "<p>Loading history...</p>";
    modal.classList.remove("hidden");

    try {
        const res = await fetch(`/api/websites/${id}/history`);
        const data = await res.json();
        if (!data.success) return;

        document.getElementById("modal-site-name").textContent = `History: ${data.website.name}`;

        if (data.history.length === 0) {
            body.innerHTML = "<p>No check history recorded yet.</p>";
            return;
        }

        body.innerHTML = data.history.map(entry => {
            let diffHtml = "";
            if (entry.diff_snippet) {
                const lines = entry.diff_snippet.split("\n").map(l => {
                    if (l.startsWith("+") && !l.startsWith("+++")) return `<span class="diff-add">${escapeHtml(l)}</span>`;
                    if (l.startsWith("-") && !l.startsWith("---")) return `<span class="diff-del">${escapeHtml(l)}</span>`;
                    return escapeHtml(l);
                }).join("\n");
                diffHtml = `<div class="diff-code">${lines}</div>`;
            }
            return `
                <div class="history-entry">
                    <div class="history-meta">
                        <span class="badge ${getBadgeClass(entry.status)}">${entry.status}</span>
                        <span>${entry.checked_at}</span>
                    </div>
                    <div>${escapeHtml(entry.summary)}</div>
                    ${diffHtml}
                </div>
            `;
        }).join("");
    } catch (err) {
        body.innerHTML = "<p>Failed to load history.</p>";
    }
}

// UI Helpers
function toggleElement(id) { document.getElementById(id).classList.toggle("hidden"); }
function closeModal() { document.getElementById("history-modal").classList.add("hidden"); }

function fillForm(name, url) {
    document.getElementById("site-name").value = name;
    document.getElementById("site-url").value = url;
    document.getElementById("add-card").classList.remove("hidden");
}

function filterWebsites() {
    const q = document.getElementById("filter-input").value.toLowerCase();
    renderTable(websites.filter(s => s.name.toLowerCase().includes(q) || s.url.toLowerCase().includes(q)));
}

function showToast(msg) {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.classList.remove("hidden");
    setTimeout(() => toast.classList.add("hidden"), 3500);
}

function escapeHtml(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
