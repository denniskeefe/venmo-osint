#!/usr/bin/env python3
"""Venmo OSINT — Flask web UI"""

import json
import threading
import time
import webbrowser
import requests
from flask import Flask, Response, jsonify, render_template_string, request

from venmo_osint import (
    SESSION,
    apply_cookie,
    clear_cookie,
    clear_session_cookies,
    cookie_status,
    fetch_profile,
    has_auth_cookie,
    load_saved_cookie,
    resolve_cookie,
    save_cookie,
    search_by_name,
    search_users,
)

app = Flask(__name__)

# ── restore saved cookie on startup ──────────────────────────────────────────
_saved = load_saved_cookie()
if _saved:
    apply_cookie(_saved)

# ── HTML ─────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Venmo OSINT</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<style>
  /* ── reset & base ─────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0d0f14;
    --surface:  #161b25;
    --card:     #1e2535;
    --border:   #2a3248;
    --accent:   #008DFF;
    --accent2:  #00d4aa;
    --danger:   #ff4f6b;
    --warn:     #f5a623;
    --text:     #e8eaf0;
    --muted:    #7b8299;
    --radius:   10px;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }

  /* ── layout ──────────────────────────────────────────────── */
  .shell   { display: flex; height: 100vh; overflow: hidden; }
  .sidebar { width: 220px; background: var(--surface); border-right: 1px solid var(--border);
             display: flex; flex-direction: column; flex-shrink: 0; }
  .main    { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }

  /* ── sidebar ─────────────────────────────────────────────── */
  .logo { padding: 24px 20px 16px; font-size: 16px; font-weight: 700;
          letter-spacing: .04em; color: var(--accent); display: flex;
          align-items: center; gap: 9px; }
  .logo svg { flex-shrink: 0; }

  nav { flex: 1; padding: 8px 10px; }
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px; border-radius: 7px; cursor: pointer;
    color: var(--muted); font-weight: 500; transition: all .15s;
    border: none; background: none; width: 100%; text-align: left;
    font-size: 13.5px;
  }
  .nav-item:hover        { background: var(--card); color: var(--text); }
  .nav-item.active       { background: rgba(0,141,255,.15); color: var(--accent); }
  .nav-item svg          { flex-shrink: 0; }

  .sidebar-footer { padding: 14px 16px; border-top: 1px solid var(--border); font-size: 12px; }
  .cookie-badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 9px; border-radius: 20px; font-size: 11px; font-weight: 600;
    margin-bottom: 8px;
  }
  .cookie-badge.on  { background: rgba(0,212,170,.12); color: var(--accent2); }
  .cookie-badge.off { background: rgba(255,79,107,.12); color: var(--danger); }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

  /* ── topbar ──────────────────────────────────────────────── */
  .topbar { padding: 16px 28px; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; gap: 12px; background: var(--surface); flex-shrink: 0; }
  .topbar h1 { font-size: 15px; font-weight: 600; }
  .topbar .sub { color: var(--muted); font-size: 12.5px; margin-left: auto; }

  /* ── content area ────────────────────────────────────────── */
  .content { flex: 1; overflow-y: auto; padding: 28px; }

  /* ── bottom nav (mobile only) ────────────────────────────── */
  .bottom-nav { display: none; }

  /* ── mobile breakpoint ───────────────────────────────────── */
  @media (max-width: 640px) {
    /* swap sidebar for bottom nav */
    .sidebar     { display: none; }
    .bottom-nav  {
      display: flex; position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
      background: var(--surface); border-top: 1px solid var(--border);
      height: 60px;
    }
    .bottom-nav-item {
      flex: 1; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 3px; border: none; background: none;
      color: var(--muted); font-size: 10px; font-weight: 600; cursor: pointer;
      transition: color .15s; padding: 6px 0;
    }
    .bottom-nav-item.active { color: var(--accent); }
    .bottom-nav-item svg    { width: 20px; height: 20px; }

    /* main fills full width; leave room for fixed bottom nav */
    .main    { width: 100%; }
    .content { padding: 16px 14px 80px; }  /* 80px = bottom nav height + gap */

    /* topbar: hide subtitle, tighten padding */
    .topbar      { padding: 12px 16px; }
    .topbar .sub { display: none; }
    .topbar h1   { font-size: 15px; }

    /* cookie badge moves into topbar on mobile */
    .topbar-badge { display: inline-flex !important; }

    /* search row stacks vertically */
    .search-row          { flex-direction: column; }
    .search-row input    { width: 100% !important; flex: none !important; }
    .search-row .btn     { width: 100%; justify-content: center; }

    /* name search: first/last on one row, limit hidden, button full width */
    #mode-name .search-row          { flex-direction: row; flex-wrap: wrap; gap: 8px; }
    #mode-name .search-row input[id="first-input"],
    #mode-name .search-row input[id="last-input"] { flex: 1 1 calc(50% - 4px) !important; min-width: 0; }
    #mode-name .search-row input[id="name-limit"] { display: none; }
    #mode-name .search-row .btn     { flex: 1 1 100%; }

    /* meta grid single column */
    .meta-grid { grid-template-columns: 1fr 1fr; }

    /* profile card header: tighter */
    .card-header { gap: 12px; }
    .avatar, .avatar-placeholder { width: 48px; height: 48px; }
    .profile-name { font-size: 16px; }

    /* result cards: truncate long IDs */
    .result-id { display: none; }
    .result-card { padding: 12px 14px; }

    /* transactions wrap nicely */
    .txn-row { gap: 6px; }

    /* cookie panel full width */
    .cookie-panel { max-width: 100%; }

    /* mode tabs scrollable */
    .mode-tabs { overflow-x: auto; width: 100%; }

    /* cards padding */
    .card { padding: 16px; }
  }

  @media (max-width: 380px) {
    .meta-grid { grid-template-columns: 1fr; }
  }

  /* ── panels ──────────────────────────────────────────────── */
  .panel { display: none; }
  .panel.active { display: block; }

  /* ── search bar ──────────────────────────────────────────── */
  .search-row { display: flex; gap: 10px; margin-bottom: 24px; }
  .search-row input {
    flex: 1; background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 11px 16px; color: var(--text);
    font-size: 14px; outline: none; transition: border .15s;
  }
  .search-row input:focus { border-color: var(--accent); }
  .search-row input::placeholder { color: var(--muted); }

  /* ── buttons ─────────────────────────────────────────────── */
  .btn {
    padding: 10px 20px; border-radius: var(--radius); border: none;
    cursor: pointer; font-size: 13.5px; font-weight: 600;
    display: inline-flex; align-items: center; gap: 7px; transition: all .15s;
  }
  .btn-primary  { background: var(--accent);  color: #fff; }
  .btn-primary:hover  { background: #0079e0; }
  .btn-success  { background: var(--accent2); color: #0d0f14; }
  .btn-success:hover  { background: #00bfa0; }
  .btn-danger   { background: var(--danger);  color: #fff; }
  .btn-danger:hover   { background: #e03050; }
  .btn-ghost {
    background: transparent; border: 1px solid var(--border); color: var(--muted);
  }
  .btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
  .btn:disabled { opacity: .45; cursor: not-allowed; }

  /* ── spinner ─────────────────────────────────────────────── */
  .spinner {
    width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.2);
    border-top-color: #fff; border-radius: 50%;
    animation: spin .6s linear infinite; flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── cards ───────────────────────────────────────────────── */
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px; margin-bottom: 16px;
  }
  .card-header { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 16px; }
  .avatar {
    width: 60px; height: 60px; border-radius: 50%;
    object-fit: cover; background: var(--border); flex-shrink: 0;
    border: 2px solid var(--border);
  }
  .avatar-placeholder {
    width: 60px; height: 60px; border-radius: 50%;
    background: var(--border); display: flex; align-items: center;
    justify-content: center; color: var(--muted); font-size: 22px; flex-shrink: 0;
  }
  .profile-name { font-size: 18px; font-weight: 700; margin-bottom: 3px; }
  .profile-handle { color: var(--accent); font-size: 13px; margin-bottom: 6px; }
  .profile-bio { color: var(--muted); font-size: 13px; }

  .meta-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 16px;
  }
  .meta-item { background: var(--surface); border-radius: 8px; padding: 12px 14px; }
  .meta-label { color: var(--muted); font-size: 11px; text-transform: uppercase;
                letter-spacing: .06em; margin-bottom: 4px; }
  .meta-value { font-size: 14px; font-weight: 600; word-break: break-all; }
  .meta-value a { color: var(--accent); text-decoration: none; }
  .meta-value a:hover { text-decoration: underline; }

  /* ── transactions ────────────────────────────────────────── */
  .txn-title { font-size: 12.5px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .07em; color: var(--muted); margin-bottom: 10px; }
  .txn-list { display: flex; flex-direction: column; gap: 8px; }
  .txn-row {
    background: var(--surface); border-radius: 8px; padding: 10px 14px;
    display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  }
  .txn-date  { color: var(--muted); font-size: 11.5px; flex-shrink: 0; }
  .txn-actor { font-weight: 600; }
  .txn-verb  { color: var(--muted); font-size: 12.5px; }
  .txn-target{ color: var(--accent2); font-weight: 600; }
  .txn-note  { color: var(--muted); font-style: italic; font-size: 12.5px; }

  /* ── search results ──────────────────────────────────────── */
  .result-card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 18px; margin-bottom: 10px;
    display: flex; align-items: center; gap: 14px; cursor: pointer;
    transition: border-color .15s, background .15s;
  }
  .result-card:hover { border-color: var(--accent); background: rgba(0,141,255,.05); }
  .result-avatar { width: 42px; height: 42px; border-radius: 50%;
                   object-fit: cover; background: var(--border); flex-shrink: 0; }
  .result-info { flex: 1; min-width: 0; }
  .result-name { font-weight: 600; margin-bottom: 2px; }
  .result-username { color: var(--accent); font-size: 12.5px; }
  .result-id { color: var(--muted); font-size: 11.5px; margin-left: auto; flex-shrink: 0; }
  .result-arrow { color: var(--muted); font-size: 16px; }

  /* ── empty / error states ────────────────────────────────── */
  .empty { text-align: center; padding: 60px 20px; color: var(--muted); }
  .empty-icon { font-size: 42px; margin-bottom: 12px; }
  .empty p { font-size: 14px; }
  .alert {
    padding: 12px 16px; border-radius: 8px; margin-bottom: 16px;
    font-size: 13.5px; display: flex; align-items: center; gap: 8px;
  }
  .alert-error { background: rgba(255,79,107,.12); border: 1px solid rgba(255,79,107,.3); color: var(--danger); }
  .alert-warn  { background: rgba(245,166,35,.12);  border: 1px solid rgba(245,166,35,.3);  color: var(--warn); }
  .alert-info  { background: rgba(0,141,255,.12);  border: 1px solid rgba(0,141,255,.3);  color: var(--accent); }

  /* ── cookie panel ────────────────────────────────────────── */
  .cookie-panel { max-width: 560px; }
  .field-label { font-size: 12.5px; color: var(--muted); margin-bottom: 6px; font-weight: 500; }
  textarea {
    width: 100%; background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px 14px; color: var(--text);
    font-size: 13px; font-family: 'Menlo', 'Consolas', monospace;
    resize: vertical; min-height: 90px; outline: none; transition: border .15s;
  }
  textarea:focus { border-color: var(--accent); }
  .cookie-actions { display: flex; gap: 10px; margin-top: 12px; }
  .hint { font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 14px;
          padding: 12px 14px; background: var(--surface); border-radius: 8px; }
  .hint code { background: var(--card); padding: 1px 5px; border-radius: 4px; font-size: 11.5px; }

  /* ── mode tabs ───────────────────────────────────────────── */
  .mode-tabs { display: flex; gap: 4px; margin-bottom: 16px;
               background: var(--surface); border-radius: 8px; padding: 4px;
               width: fit-content; }
  .mode-tab {
    padding: 7px 18px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 13px; font-weight: 600; background: transparent;
    color: var(--muted); transition: all .15s;
  }
  .mode-tab.active { background: var(--card); color: var(--text); }
  .mode-tab:hover:not(.active) { color: var(--text); }

  .search-hint {
    font-size: 12px; color: var(--muted); margin-bottom: 18px;
    padding: 9px 13px; background: var(--surface); border-radius: 7px;
  }
  .search-hint code { background: var(--card); padding: 1px 5px; border-radius: 4px; }

  /* ── source badge ─────────────────────────────────────────── */
  .source-badge {
    font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 20px;
    text-transform: uppercase; letter-spacing: .05em; margin-left: auto; flex-shrink: 0;
  }
  .source-ddg     { background: rgba(255,107,53,.15); color: #ff6b35; }
  .source-pattern { background: rgba(0,212,170,.12);  color: var(--accent2); }
  .source-venmo   { background: rgba(0,141,255,.12);  color: var(--accent); }

  /* ── permission modal ────────────────────────────────────── */
  .modal-backdrop {
    display: none; position: fixed; inset: 0; z-index: 200;
    background: rgba(0,0,0,.7); backdrop-filter: blur(4px);
    align-items: center; justify-content: center; padding: 20px;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 14px; padding: 28px; max-width: 420px; width: 100%;
    box-shadow: 0 24px 60px rgba(0,0,0,.6);
    animation: modal-in .2s ease;
  }
  @keyframes modal-in {
    from { opacity: 0; transform: scale(.95) translateY(8px); }
    to   { opacity: 1; transform: none; }
  }
  .modal-icon {
    width: 48px; height: 48px; border-radius: 12px; margin-bottom: 16px;
    background: rgba(0,141,255,.12); display: flex; align-items: center;
    justify-content: center; color: var(--accent);
  }
  .modal-title { font-size: 17px; font-weight: 700; margin-bottom: 8px; }
  .modal-body  { color: var(--muted); font-size: 13.5px; line-height: 1.6; margin-bottom: 20px; }
  .modal-body strong { color: var(--text); }
  .modal-permissions {
    background: var(--surface); border-radius: 8px; padding: 12px 14px;
    margin-bottom: 20px; display: flex; flex-direction: column; gap: 8px;
  }
  .perm-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
  .perm-icon { color: var(--accent2); flex-shrink: 0; }
  .modal-browser-row {
    display: flex; gap: 8px; margin-bottom: 20px;
  }
  .browser-btn {
    flex: 1; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--surface); color: var(--muted); font-size: 12.5px;
    font-weight: 600; cursor: pointer; transition: all .15s; text-align: center;
  }
  .browser-btn.selected { border-color: var(--accent); color: var(--accent); background: rgba(0,141,255,.1); }
  .modal-save-row { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; font-size: 13px; color: var(--muted); }
  .modal-save-row input[type=checkbox] { accent-color: var(--accent); width: 16px; height: 16px; cursor: pointer; }
  .modal-actions { display: flex; gap: 10px; }
  .modal-actions .btn { flex: 1; justify-content: center; }

  /* ── export bar ─────────────────────────────────────────── */
  .export-bar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-top: 4px; padding: 10px 14px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .export-btn {
    padding: 6px 14px; font-size: 12px; gap: 5px;
  }
  .export-btn.copied { border-color: var(--accent2); color: var(--accent2); }

  /* ── misc ────────────────────────────────────────────────── */
  ::-webkit-scrollbar       { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="shell">

  <!-- SIDEBAR -->
  <aside class="sidebar">
    <div class="logo">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      Venmo OSINT
    </div>

    <nav>
      <button class="nav-item active" onclick="showPanel('profile')" id="nav-profile">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
        Profile Lookup
      </button>
      <button class="nav-item" onclick="showPanel('search')" id="nav-search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        Search Users
      </button>
      <button class="nav-item" onclick="showPanel('cookie')" id="nav-cookie">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        Cookie / Auth
      </button>
    </nav>

    <div class="sidebar-footer">
      <div class="cookie-badge" id="ck-badge">
        <span class="dot"></span><span id="ck-label">checking…</span>
      </div>
      <div style="color:var(--muted);font-size:11px">Public data only</div>
    </div>
  </aside>

  <!-- PERMISSION MODAL -->
  <div class="modal-backdrop" id="grab-modal">
    <div class="modal">
      <div class="modal-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </div>
      <div class="modal-title">Permission to read browser cookies</div>
      <div class="modal-body">
        This tool wants to read your <strong>Venmo session cookies</strong> from your local browser profile so you don't have to copy them manually.
      </div>

      <div class="modal-permissions">
        <div class="perm-row">
          <svg class="perm-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          Read cookies for <strong style="color:var(--text);margin:0 4px">venmo.com</strong> only
        </div>
        <div class="perm-row">
          <svg class="perm-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          Runs entirely on your machine — nothing is sent externally
        </div>
        <div class="perm-row">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          <span style="color:var(--muted)">Does not access passwords, history, or other sites</span>
        </div>
      </div>

      <div class="modal-body" style="margin-bottom:12px;font-size:13px">Select your browser:</div>
      <div class="modal-browser-row">
        <button class="browser-btn selected" id="bb-chrome"  onclick="selectBrowser('chrome')">Chrome</button>
        <button class="browser-btn"          id="bb-firefox" onclick="selectBrowser('firefox')">Firefox</button>
        <button class="browser-btn"          id="bb-brave"   onclick="selectBrowser('brave')">Brave</button>
      </div>

      <label class="modal-save-row">
        <input type="checkbox" id="grab-save" checked/>
        Save cookie to <code style="font-size:11.5px;background:var(--surface);padding:1px 5px;border-radius:4px">~/.venmo_osint</code> for future runs
      </label>

      <div class="modal-actions">
        <button class="btn btn-ghost" onclick="closeGrabModal()">Cancel</button>
        <button class="btn btn-primary" onclick="confirmGrab()" id="grab-confirm-btn">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Allow &amp; Grab Cookie
        </button>
      </div>
    </div>
  </div>

  <!-- BOTTOM NAV (mobile) -->
  <nav class="bottom-nav">
    <button class="bottom-nav-item active" id="bnav-profile" onclick="showPanel('profile')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
        <circle cx="12" cy="7" r="4"/>
      </svg>
      Profile
    </button>
    <button class="bottom-nav-item" id="bnav-search" onclick="showPanel('search')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
      Search
    </button>
    <button class="bottom-nav-item" id="bnav-cookie" onclick="showPanel('cookie')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
      Auth
    </button>
  </nav>

  <!-- MAIN -->
  <div class="main">
    <div class="topbar">
      <h1 id="panel-title">Profile Lookup</h1>
      <div class="cookie-badge off topbar-badge" id="ck-badge-top" style="display:none;margin-left:auto">
        <span class="dot"></span><span id="ck-label-top">No cookie</span>
      </div>
      <span class="sub" id="panel-sub">Enter a Venmo username to retrieve public info</span>
    </div>

    <div class="content">

      <!-- ── PROFILE PANEL ─────────────────────────────────── -->
      <div class="panel active" id="panel-profile">
        <div class="search-row">
          <input id="profile-input" placeholder="Username (e.g. venmo)"
                 onkeydown="if(event.key==='Enter') lookupProfile()"/>
          <button class="btn btn-primary" onclick="lookupProfile()" id="profile-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            Look Up
          </button>
        </div>
        <div id="profile-results"></div>
      </div>

      <!-- ── SEARCH PANEL ──────────────────────────────────── -->
      <div class="panel" id="panel-search">

        <!-- mode tabs -->
        <div class="mode-tabs">
          <button class="mode-tab active" id="tab-name"     onclick="setMode('name')">By Name</button>
          <button class="mode-tab"        id="tab-username" onclick="setMode('username')">By Username / Keyword</button>
        </div>

        <!-- name mode -->
        <div id="mode-name">
          <div class="search-row">
            <input id="first-input" placeholder="First name" style="flex:.9"
                   onkeydown="if(event.key==='Enter') runSearch()"/>
            <input id="last-input"  placeholder="Last name"  style="flex:.9"
                   onkeydown="if(event.key==='Enter') runSearch()"/>
            <input id="name-limit"  type="number" value="20" min="1" max="50"
                   style="width:75px" placeholder="Limit"/>
            <button class="btn btn-primary" onclick="runSearch()" id="search-btn">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              Search
            </button>
          </div>
          <div class="search-hint">
            🔍 Searches DuckDuckGo (<code>site:venmo.com/u</code>) + tries common username patterns — no cookie needed.
          </div>
        </div>

        <!-- keyword / username mode -->
        <div id="mode-username" style="display:none">
          <div class="search-row">
            <input id="search-input" placeholder="Username or keyword (cookie required for full results)"
                   onkeydown="if(event.key==='Enter') runSearch()"/>
            <input id="search-limit" type="number" value="20" min="1" max="50"
                   style="width:75px" placeholder="Limit"/>
            <button class="btn btn-primary" onclick="runSearch()" id="search-btn-kw">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              Search
            </button>
          </div>
        </div>

        <div id="search-results"></div>
      </div>

      <!-- ── COOKIE PANEL ──────────────────────────────────── -->
      <div class="panel" id="panel-cookie">
        <div class="cookie-panel">
          <div class="card">
            <div style="font-size:15px;font-weight:700;margin-bottom:4px">Session Cookie</div>
            <div style="color:var(--muted);font-size:13px;margin-bottom:18px">
              Required for search. Profile lookup works without it.
            </div>
            <div id="grab-btn-area"></div>

            <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
              <div style="flex:1;height:1px;background:var(--border)"></div>
              <span style="color:var(--muted);font-size:11.5px;font-weight:600">OR PASTE MANUALLY</span>
              <div style="flex:1;height:1px;background:var(--border)"></div>
            </div>

            <div class="field-label">Cookie string</div>
            <textarea id="cookie-input" placeholder='venmo_device_id=abc123; _venmoid=xyz789; ...'></textarea>
            <div class="cookie-actions">
              <button class="btn btn-success" onclick="saveCookie()">Save &amp; Apply</button>
              <button class="btn btn-danger btn-ghost" onclick="clearCookie()" style="background:transparent;border:1px solid var(--border);color:var(--muted)">Clear</button>
            </div>
            <div id="cookie-msg"></div>
          </div>

          <div class="hint">
            <strong>How to grab your Venmo cookie</strong><br><br>
            1. Log in to <strong>venmo.com</strong> in Chrome<br>
            2. Open DevTools → <code>F12</code> → <strong>Network</strong> tab<br>
            3. Reload the page, click any <code>venmo.com</code> request<br>
            4. In <strong>Headers</strong> → find <code>Cookie:</code> under Request Headers<br>
            5. Copy the full value and paste it above<br><br>
            The cookie is saved to <code>~/.venmo_osint</code> (chmod 600).
          </div>
        </div>
      </div>

    </div><!-- /content -->
  </div><!-- /main -->
</div><!-- /shell -->

<script>
// ── panel switching ──────────────────────────────────────────────────────────
const PANELS = {
  profile: { title:'Profile Lookup',  sub:'Enter a Venmo username to retrieve public info' },
  search:  { title:'Search Users',    sub:'Find Venmo accounts by name or keyword' },
  cookie:  { title:'Cookie / Auth',   sub:'Store a session cookie to unlock full search' },
};

function showPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.bottom-nav-item').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  const bnav = document.getElementById('bnav-' + name);
  if (bnav) bnav.classList.add('active');
  document.getElementById('panel-title').textContent = PANELS[name].title;
  document.getElementById('panel-sub').textContent   = PANELS[name].sub;
  // scroll content to top on navigation
  document.querySelector('.content').scrollTop = 0;
}

// ── cookie badge ────────────────────────────────────────────────────────────
async function refreshBadge() {
  const res  = await fetch('/api/cookie/status');
  const data = await res.json();
  // sidebar badge
  const badge = document.getElementById('ck-badge');
  const label = document.getElementById('ck-label');
  // topbar badge (mobile)
  const badgeTop = document.getElementById('ck-badge-top');
  const labelTop = document.getElementById('ck-label-top');
  if (data.active) {
    badge.className = 'cookie-badge on';
    label.textContent = 'Cookie active';
    badgeTop.className = 'cookie-badge on topbar-badge';
    labelTop.textContent = 'Cookie active';
  } else {
    badge.className = 'cookie-badge off';
    label.textContent = 'No cookie';
    badgeTop.className = 'cookie-badge off topbar-badge';
    labelTop.textContent = 'No cookie';
  }
}
refreshBadge();

// ── capabilities check (grab-from-browser only works locally) ────────────────
async function initCapabilities() {
  try {
    const res  = await fetch('/api/cookie/capabilities');
    const caps = await res.json();
    const area = document.getElementById('grab-btn-area');
    if (caps.grab_available) {
      area.innerHTML = `
        <button class="btn btn-primary" onclick="openGrabModal()" style="width:100%;justify-content:center;margin-bottom:16px">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Grab from Browser
        </button>`;
    } else {
      area.innerHTML = `
        <div class="alert alert-info" style="margin-bottom:16px">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="flex-shrink:0">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span><strong>Grab from Browser</strong> is only available when running locally.
          Paste your cookie manually below, or
          <a href="https://github.com/denniskeefe/venmo-osint" target="_blank" style="color:inherit">run the app on your machine</a>.</span>
        </div>`;
    }
  } catch(e) { /* silently ignore */ }
}
initCapabilities();

// ── profile lookup ───────────────────────────────────────────────────────────
async function lookupProfile() {
  const input = document.getElementById('profile-input');
  const username = input.value.trim().replace(/^@/, '');
  if (!username) { input.focus(); return; }

  const btn = document.getElementById('profile-btn');
  const out  = document.getElementById('profile-results');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Looking up…';
  out.innerHTML = '';

  try {
    const res  = await fetch('/api/profile/' + encodeURIComponent(username));
    const data = await res.json();
    _lastProfile = data;
    out.innerHTML = renderProfile(data);
  } catch(e) {
    out.innerHTML = alertHtml('error', 'Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Look Up`;
  }
}

let _lastProfile = null;

function renderProfile(p) {
  if (p.error) return alertHtml('error', p.error);

  const avatar = p.profile_picture_url
    ? `<img class="avatar" src="${esc(p.profile_picture_url)}" onerror="this.replaceWith(makePlaceholder())">`
    : `<div class="avatar-placeholder">👤</div>`;

  const metas = [
    { label:'User ID',        value: p.id || '—' },
    { label:'First name',     value: p.first_name || null },
    { label:'Last name',      value: p.last_name  || null },
    { label:'Friend count',   value: p.friend_count != null ? p.friend_count : null },
    { label:'Member since',   value: p.date_joined || null },
    { label:'Account type',   value: p.identity_type || (p.is_business ? 'Business' : null) },
    { label:'Active',         value: p.is_active === false ? 'No (deactivated)' : null },
    { label:'Profile URL',    value: `<a href="${esc(p.profile_url)}" target="_blank">${esc(p.profile_url)}</a>` },
  ].filter(m => m.value).map(m => `
    <div class="meta-item">
      <div class="meta-label">${m.label}</div>
      <div class="meta-value">${m.value}</div>
    </div>`).join('');

  const txns = (p.recent_transactions || []).map(t => `
    <div class="txn-row">
      <span class="txn-date">${esc(t.date ? t.date.slice(0,10) : '')}</span>
      <span class="txn-actor">${esc(t.actor || '?')}</span>
      <span class="txn-verb">${esc(t.type || 'paid')}</span>
      <span class="txn-target">${esc(t.target || '?')}</span>
      <span class="txn-note">"${esc(t.note || '')}"</span>
    </div>`).join('');

  let txnBlock;
  if (txns) {
    txnBlock = `<div class="txn-title">Recent public transactions</div><div class="txn-list">${txns}</div>`;
  } else if (p.transactions_note) {
    txnBlock = `<div class="txn-title">Recent public transactions</div>${alertHtml('warn', p.transactions_note)}`;
  } else {
    txnBlock = `<div style="color:var(--muted);font-size:13px">No public transactions visible.</div>`;
  }

  const noteBlock = p.note ? alertHtml('warn', p.note) : '';

  return `
    ${noteBlock}
    <div class="card">
      <div class="card-header">
        ${avatar}
        <div style="flex:1;min-width:0">
          <div class="profile-name">${esc(p.display_name || p.username)}</div>
          <div class="profile-handle">@${esc(p.username)}</div>
          ${p.bio ? `<div class="profile-bio">${esc(p.bio)}</div>` : ''}
        </div>
      </div>
      <div class="meta-grid">${metas}</div>
      ${txnBlock}
    </div>
    <div class="export-bar">
      <span style="color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.04em">EXPORT</span>
      <button class="btn btn-ghost export-btn" onclick="exportJSON()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        JSON
      </button>
      <button class="btn btn-ghost export-btn" onclick="exportTXT()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        TXT
      </button>
      <button class="btn btn-ghost export-btn" onclick="exportCSV()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        CSV
      </button>
      <button class="btn btn-ghost export-btn" onclick="exportPDF()" id="pdf-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        PDF
      </button>
      <button class="btn btn-ghost export-btn" onclick="copyClipboard()" id="copy-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        Copy
      </button>
    </div>`;
}

// ── search mode toggle ────────────────────────────────────────────────────────
let _searchMode = 'name';
function setMode(mode) {
  _searchMode = mode;
  document.getElementById('tab-name').classList.toggle('active',     mode === 'name');
  document.getElementById('tab-username').classList.toggle('active', mode === 'username');
  document.getElementById('mode-name').style.display     = mode === 'name'     ? '' : 'none';
  document.getElementById('mode-username').style.display = mode === 'username' ? '' : 'none';
  document.getElementById('search-results').innerHTML = '';
}

// ── unified search dispatcher ─────────────────────────────────────────────────
async function runSearch() {
  if (_searchMode === 'name') await searchByName();
  else                        await searchByKeyword();
}

async function searchByName() {
  const first = document.getElementById('first-input').value.trim();
  const last  = document.getElementById('last-input').value.trim();
  const limit = parseInt(document.getElementById('name-limit').value) || 10;
  if (!first && !last) { document.getElementById('first-input').focus(); return; }

  const btn = document.getElementById('search-btn');
  const out  = document.getElementById('search-results');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Searching…';
  out.innerHTML = '';

  try {
    const url = `/api/search/name?first=${encodeURIComponent(first)}&last=${encodeURIComponent(last)}&limit=${limit}`;
    const res  = await fetch(url);
    const data = await res.json();
    out.innerHTML = renderSearch(data);
  } catch(e) {
    out.innerHTML = alertHtml('error', 'Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Search`;
  }
}

async function searchByKeyword() {
  const query = document.getElementById('search-input').value.trim();
  const limit = parseInt(document.getElementById('search-limit').value) || 10;
  if (!query) { document.getElementById('search-input').focus(); return; }

  const btn = document.getElementById('search-btn-kw');
  const out  = document.getElementById('search-results');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Searching…';
  out.innerHTML = '';

  try {
    const res  = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=${limit}`);
    const data = await res.json();
    out.innerHTML = renderSearch(data);
  } catch(e) {
    out.innerHTML = alertHtml('error', 'Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Search`;
  }
}

function renderSearch(results) {
  if (!results.length) return emptyState('No results found.');

  return results.map(r => {
    if (r.error) return alertHtml('error', r.error);
    if (r.note)  return alertHtml('warn',  r.note);
    const avatar = r.profile_picture_url
      ? `<img class="result-avatar" src="${esc(r.profile_picture_url)}" onerror="this.style.display='none'">`
      : `<div class="result-avatar" style="display:flex;align-items:center;justify-content:center;color:var(--muted)">👤</div>`;
    const srcMap = { duckduckgo:'source-ddg', pattern_guess:'source-pattern', venmo:'source-venmo' };
    const srcLabel = { duckduckgo:'DDG', pattern_guess:'Pattern', venmo:'Venmo' };
    const src = r._source || '';
    const badge = src ? `<span class="source-badge ${srcMap[src]||''}">${srcLabel[src]||src}</span>` : '';
    const snippet = r.snippet ? `<div style="color:var(--muted);font-size:11.5px;margin-top:3px">${esc(r.snippet)}</div>` : '';
    return `
      <div class="result-card" onclick="jumpToProfile('${esc(r.username)}')">
        ${avatar}
        <div class="result-info">
          <div class="result-name">${esc(r.display_name || r.username)}</div>
          <div class="result-username">@${esc(r.username)}</div>
          ${snippet}
        </div>
        ${badge}
        <span class="result-id" style="margin-left:8px">${esc(r.id || '')}</span>
        <span class="result-arrow">›</span>
      </div>`;
  }).join('');
}

function jumpToProfile(username) {
  document.getElementById('profile-input').value = username;
  showPanel('profile');
  lookupProfile();
}

// ── cookie management ────────────────────────────────────────────────────────
async function saveCookie() {
  const val = document.getElementById('cookie-input').value.trim();
  if (!val) return;
  const res  = await fetch('/api/cookie/save', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ cookie: val }),
  });
  const data = await res.json();
  const msg  = document.getElementById('cookie-msg');
  if (data.ok) {
    msg.innerHTML = alertHtml('info', '✓ Cookie saved and applied.');
    refreshBadge();
  } else {
    msg.innerHTML = alertHtml('error', data.error || 'Failed to save.');
  }
}

async function clearCookie() {
  const res  = await fetch('/api/cookie/clear', { method:'POST' });
  const data = await res.json();
  const msg  = document.getElementById('cookie-msg');
  document.getElementById('cookie-input').value = '';
  msg.innerHTML = data.ok ? alertHtml('info', '✓ Cookie cleared.') : alertHtml('error', data.error);
  refreshBadge();
}

// ── grab-from-browser modal ───────────────────────────────────────────────────
let _selectedBrowser = 'chrome';

function openGrabModal() {
  document.getElementById('grab-modal').classList.add('open');
}
function closeGrabModal() {
  document.getElementById('grab-modal').classList.remove('open');
}
function selectBrowser(b) {
  _selectedBrowser = b;
  ['chrome','firefox','brave'].forEach(n => {
    document.getElementById('bb-' + n).classList.toggle('selected', n === b);
  });
}

async function confirmGrab() {
  const btn  = document.getElementById('grab-confirm-btn');
  const save = document.getElementById('grab-save').checked;
  const msg  = document.getElementById('cookie-msg');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Grabbing…';

  try {
    const res  = await fetch('/api/cookie/grab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ browser: _selectedBrowser, save }),
    });
    const data = await res.json();

    closeGrabModal();

    if (data.ok) {
      msg.innerHTML = alertHtml('info',
        `✓ Grabbed ${data.count} cookies from ${_selectedBrowser}` +
        (data.saved ? ' and saved to ~/.venmo_osint.' : '.') +
        ` Keys: ${data.keys.slice(0,4).join(', ')}…`
      );
      refreshBadge();
    } else {
      msg.innerHTML = alertHtml('error', data.error || 'Failed to grab cookie.');
    }
  } catch(e) {
    closeGrabModal();
    msg.innerHTML = alertHtml('error', 'Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg> Allow &amp; Grab Cookie`;
  }
}

// close modal on backdrop click
document.getElementById('grab-modal').addEventListener('click', function(e) {
  if (e.target === this) closeGrabModal();
});

// ── export ───────────────────────────────────────────────────────────────────
function _download(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function _profileFilename(ext) {
  const u = (_lastProfile && _lastProfile.username) || 'profile';
  return `venmo_${u}_${new Date().toISOString().slice(0,10)}.${ext}`;
}

function exportJSON() {
  if (!_lastProfile) return;
  _download(_profileFilename('json'), JSON.stringify(_lastProfile, null, 2), 'application/json');
}

function exportTXT() {
  if (!_lastProfile) return;
  const p = _lastProfile;
  const lines = [
    '='.repeat(55),
    `  Venmo Profile: @${p.username || ''}`,
    '='.repeat(55),
  ];
  const fields = [
    ['Display name',  p.display_name],
    ['First name',    p.first_name],
    ['Last name',     p.last_name],
    ['User ID',       p.id],
    ['Bio',           p.bio],
    ['Account type',  p.identity_type || (p.is_business ? 'Business' : null)],
    ['Active',        p.is_active === false ? 'No (deactivated)' : null],
    ['Member since',  p.date_joined],
    ['Friend count',  p.friend_count != null ? p.friend_count : null],
    ['Profile URL',   p.profile_url],
    ['Avatar URL',    p.profile_picture_url],
  ];
  for (const [label, val] of fields) {
    if (val != null && val !== '') lines.push(`  ${label.padEnd(20)} ${val}`);
  }
  const txns = p.recent_transactions || [];
  if (txns.length) {
    lines.push('', `  Recent transactions (${txns.length}):`);
    for (const t of txns) {
      const d = (t.date || '').slice(0, 10);
      lines.push(`    [${d}] ${t.actor || '?'} ${t.type || 'paid'} ${t.target || '?'}: "${t.note || ''}"`);
    }
  }
  lines.push('', `  Exported: ${new Date().toISOString()}`, '');
  _download(_profileFilename('txt'), lines.join('\n'), 'text/plain');
}

function exportCSV() {
  if (!_lastProfile) return;
  const p = _lastProfile;
  const rows = [
    ['field', 'value'],
    ['username',      p.username],
    ['display_name',  p.display_name],
    ['first_name',    p.first_name],
    ['last_name',     p.last_name],
    ['id',            p.id],
    ['bio',           p.bio],
    ['identity_type', p.identity_type],
    ['is_business',   p.is_business],
    ['is_active',     p.is_active],
    ['date_joined',   p.date_joined],
    ['friend_count',  p.friend_count],
    ['profile_url',   p.profile_url],
    ['profile_picture_url', p.profile_picture_url],
    ['exported_at',   new Date().toISOString()],
  ];
  // append transactions as extra rows
  (p.recent_transactions || []).forEach((t, i) => {
    rows.push([`txn_${i+1}`, `${(t.date||'').slice(0,10)} | ${t.actor||''} ${t.type||'paid'} ${t.target||''} | "${t.note||''}"`]);
  });
  const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
  _download(_profileFilename('csv'), csv, 'text/csv');
}

// ── PDF export ───────────────────────────────────────────────────────────────
async function _imageToDataURL(url) {
  try {
    const proxied = '/api/image-proxy?url=' + encodeURIComponent(url);
    const res = await fetch(proxied);
    if (!res.ok) return null;
    const blob = await res.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch (e) {
    return null;
  }
}

async function exportPDF() {
  if (!_lastProfile) return;
  const p = _lastProfile;
  const btn = document.getElementById('pdf-btn');
  const origHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';

  try {
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: 'pt', format: 'a4' });
    const pageWidth  = doc.internal.pageSize.getWidth();
    const margin     = 40;
    let   y          = 50;

    // ── header bar ──────────────────────────────────────────────
    doc.setFillColor(0, 13, 26);
    doc.rect(0, 0, pageWidth, 70, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(16);
    doc.text('Venmo OSINT — Profile Report', margin, 35);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(180, 200, 220);
    doc.text(`Generated: ${new Date().toLocaleString()}`, margin, 52);

    y = 100;

    // ── avatar ──────────────────────────────────────────────────
    let avatarSize = 0;
    if (p.profile_picture_url) {
      const dataUrl = await _imageToDataURL(p.profile_picture_url);
      if (dataUrl) {
        try {
          avatarSize = 80;
          doc.addImage(dataUrl, margin, y, avatarSize, avatarSize, undefined, 'FAST');
        } catch (e) { avatarSize = 0; }
      }
    }

    // ── name / handle / bio (to the right of avatar) ───────────
    const textX = avatarSize ? margin + avatarSize + 16 : margin;
    let ty = y + 18;
    doc.setTextColor(20, 20, 30);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.text(p.display_name || p.username || '—', textX, ty);
    ty += 20;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(12);
    doc.setTextColor(0, 141, 255);
    doc.text(`@${p.username || '—'}`, textX, ty);
    ty += 18;
    if (p.bio) {
      doc.setTextColor(100, 105, 120);
      doc.setFontSize(10);
      const bioLines = doc.splitTextToSize(p.bio, pageWidth - textX - margin);
      doc.text(bioLines, textX, ty);
      ty += bioLines.length * 12;
    }

    y = Math.max(y + avatarSize, ty) + 20;

    // ── divider ──────────────────────────────────────────────────
    doc.setDrawColor(220, 224, 232);
    doc.line(margin, y, pageWidth - margin, y);
    y += 24;

    // ── field table ─────────────────────────────────────────────
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.setTextColor(20, 20, 30);
    doc.text('Profile Details', margin, y);
    y += 18;

    const fields = [
      ['Username',      p.username],
      ['Display name',  p.display_name],
      ['First name',    p.first_name],
      ['Last name',     p.last_name],
      ['User ID',       p.id],
      ['Account type',  p.identity_type || (p.is_business ? 'Business' : (p.is_business === false ? 'Personal' : null))],
      ['Active',        p.is_active === false ? 'No (deactivated)' : (p.is_active === true ? 'Yes' : null)],
      ['Member since',  p.date_joined],
      ['Friend count',  p.friend_count != null ? String(p.friend_count) : null],
      ['Profile URL',   p.profile_url],
      ['Avatar URL',    p.profile_picture_url],
    ].filter(([, v]) => v != null && v !== '');

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    const labelW = 120;
    for (const [label, value] of fields) {
      if (y > 760) { doc.addPage(); y = 50; }
      doc.setFont('helvetica', 'bold');
      doc.setTextColor(80, 85, 100);
      doc.text(label, margin, y);
      doc.setFont('helvetica', 'normal');
      doc.setTextColor(20, 20, 30);
      const valueLines = doc.splitTextToSize(String(value), pageWidth - margin - labelW - margin);
      doc.text(valueLines, margin + labelW, y);
      y += Math.max(16, valueLines.length * 14);
    }

    // ── transactions ─────────────────────────────────────────────
    const txns = p.recent_transactions || [];
    y += 14;
    if (y > 740) { doc.addPage(); y = 50; }
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.setTextColor(20, 20, 30);
    doc.text(`Recent Public Transactions (${txns.length})`, margin, y);
    y += 18;

    if (!txns.length) {
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(10);
      doc.setTextColor(120, 125, 140);
      doc.text('No public transactions visible.', margin, y);
      y += 16;
    } else {
      doc.setFontSize(9);
      for (const t of txns) {
        if (y > 770) { doc.addPage(); y = 50; }
        const date   = (t.date || '').slice(0, 10);
        const actor  = t.actor  || '?';
        const target = t.target || '?';
        const action = t.type   || 'paid';
        const note   = t.note   || '';

        doc.setFont('helvetica', 'bold');
        doc.setTextColor(20, 20, 30);
        doc.text(`${date}`, margin, y);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(60, 65, 80);
        doc.text(`${actor}  ${action}  ${target}`, margin + 70, y);
        y += 13;
        if (note) {
          doc.setTextColor(120, 125, 140);
          const noteLines = doc.splitTextToSize(`"${note}"`, pageWidth - margin * 2 - 70);
          doc.text(noteLines, margin + 70, y);
          y += noteLines.length * 12;
        }
        y += 4;
      }
    }

    // ── footer ──────────────────────────────────────────────────
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(160, 165, 180);
      doc.text('Generated by Venmo OSINT — public data only', margin, 820);
      doc.text(`Page ${i} of ${pageCount}`, pageWidth - margin - 60, 820);
    }

    doc.save(_profileFilename('pdf'));
  } catch (e) {
    alert('PDF export failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHTML;
  }
}

async function copyClipboard() {
  if (!_lastProfile) return;
  await navigator.clipboard.writeText(JSON.stringify(_lastProfile, null, 2));
  const btn = document.getElementById('copy-btn');
  if (!btn) return;
  btn.classList.add('copied');
  btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Copied!`;
  setTimeout(() => {
    btn.classList.remove('copied');
    btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
  }, 2000);
}

// ── helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function alertHtml(type, msg) {
  const icons = { error:'✕', warn:'⚠', info:'ℹ' };
  return `<div class="alert alert-${type}">${icons[type] || ''} ${esc(msg)}</div>`;
}
function emptyState(msg) {
  return `<div class="empty"><div class="empty-icon">🔍</div><p>${esc(msg)}</p></div>`;
}
function makePlaceholder() {
  const d = document.createElement('div');
  d.className = 'avatar-placeholder';
  d.textContent = '👤';
  return d;
}
</script>
</body>
</html>
"""


# ── Global error handlers (ensure /api/* always returns JSON) ─────────────────

import traceback

@app.errorhandler(Exception)
def handle_exception(e):
    if request.path.startswith("/api/"):
        tb = traceback.format_exc()
        app.logger.error("Unhandled exception on %s:\n%s", request.path, tb)
        return jsonify({"error": f"Internal server error: {type(e).__name__}: {e}"}), 500
    raise e

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template_string(HTML)

@app.errorhandler(405)
def handle_405(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Method not allowed"}), 405
    raise e


# ── API routes ────────────────────────────────────────────────────────────────

@app.after_request
def add_no_cache_headers(resp):
    """Prevent the browser from serving a stale copy of the page/JS."""
    # Let the image proxy keep its long-lived cache (avatars rarely change)
    if request.path.startswith("/api/image-proxy"):
        return resp
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/profile/<username>")
def api_profile(username):
    return jsonify(fetch_profile(username))


@app.route("/api/image-proxy")
def api_image_proxy():
    """
    Proxy a Venmo profile picture so the browser can embed it in a
    PDF/canvas without hitting CORS restrictions on pics-v3.venmo.com.
    Only allows venmo.com / venmo CDN image URLs.
    """
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "Missing url"}), 400

    allowed_hosts = ("pics-v3.venmo.com", "s3.amazonaws.com", "venmo.com")
    if not any(h in url for h in allowed_hosts) or not url.startswith("https://"):
        return jsonify({"error": "URL not allowed"}), 400

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502

    return Response(
        resp.content,
        mimetype=resp.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.route("/api/search/name")
def api_search_name():
    first = request.args.get("first", "").strip()
    last  = request.args.get("last",  "").strip()
    limit = int(request.args.get("limit", 10))
    if not first and not last:
        return jsonify([{"error": "Provide at least a first or last name"}])
    return jsonify(search_by_name(first, last, limit=limit))


@app.route("/api/search")
def api_search():
    q     = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 10))
    if not q:
        return jsonify([{"error": "Missing query parameter 'q'"}])
    return jsonify(search_users(q, limit=limit))


@app.route("/api/cookie/status")
def api_cookie_status():
    status = cookie_status()
    return jsonify({"active": "not set" not in status, "detail": status})


@app.route("/api/cookie/save", methods=["POST"])
def api_cookie_save():
    data = request.get_json(silent=True) or {}
    cookie = (data.get("cookie") or "").strip()
    if not cookie:
        return jsonify({"ok": False, "error": "Empty cookie"})
    save_cookie(cookie)
    apply_cookie(cookie)
    return jsonify({"ok": True})


@app.route("/api/cookie/capabilities")
def api_cookie_capabilities():
    return jsonify({"grab_available": True})


@app.route("/api/cookie/grab", methods=["POST"])
def api_cookie_grab():
    """Read Venmo cookies directly from the local Chrome profile."""
    data = request.get_json(silent=True) or {}
    browser = data.get("browser", "chrome").lower()
    save = data.get("save", False)

    try:
        import browser_cookie3
        if browser == "firefox":
            jar = browser_cookie3.firefox(domain_name=".venmo.com")
        else:
            jar = browser_cookie3.chrome(domain_name=".venmo.com")

        cookies = {c.name: c.value for c in jar}
        if not cookies:
            return jsonify({"ok": False, "error": f"No Venmo cookies found in {browser}. Make sure you're logged in to venmo.com."})

        # Format as a Cookie header string
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        apply_cookie(cookie_str)
        if save:
            save_cookie(cookie_str)

        return jsonify({
            "ok": True,
            "count": len(cookies),
            "keys": list(cookies.keys()),
            "saved": save,
        })
    except ImportError:
        return jsonify({"ok": False, "error": "browser-cookie3 not installed. Run: pip3 install browser-cookie3"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/cookie/clear", methods=["POST"])
def api_cookie_clear():
    clear_cookie()
    clear_session_cookies()
    return jsonify({"ok": True})


# ── launch ────────────────────────────────────────────────────────────────────

def open_browser():
    time.sleep(0.8)
    webbrowser.open("http://127.0.0.1:5050")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    print("  Venmo OSINT GUI → http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, debug=False)
