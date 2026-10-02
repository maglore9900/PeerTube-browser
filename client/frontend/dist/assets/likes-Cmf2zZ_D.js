import"./api-base-ouyYHZ10.js";/* empty css               */import{t as h,d as p,e as s,v}from"./video-card-CoMUkQb_.js";import{i as g,s as y}from"./reactions-T0agINKk.js";import{f as L}from"./user-profile-efaQ4fUv.js";import"./safe-url-hDO6pUEa.js";function d(t){const e=document.getElementById(t);if(!e)throw new Error(`Missing likes page element: ${t}`);return e}const r=d("likes-grid"),l=d("likes-status"),c=new URLSearchParams(window.location.search).get("api")??"";r.addEventListener("click",t=>{var i;const e=(i=t.target)==null?void 0:i.closest(".like-remove");e&&b(e)});$();async function $(){l.textContent="Loading...";try{await g(c).catch(e=>{console.warn("[likes] import failed; the local likes are kept for the next load",e)});const t=await L(c);l.textContent="",r.innerHTML=m(t)}catch(t){l.textContent=t instanceof Error?t.message:"Could not load your likes"}}function m(t){return t.length?t.map(e=>{const i=e.title??"Untitled",n=h(e),a=e.instance_domain??e.instanceDomain??"",o=p(e),u=a?`${o} · ${a}`:o,k=n?`<img src="${s(n)}" alt="${s(i)}" loading="lazy" />`:'<div class="thumb-fallback">No preview</div>',f=e.video_uuid??e.videoUuid??"";return`
        <article class="like-card">
          <a class="like-link" href="${s(v(e))}">
            <div class="like-thumb">${k}</div>
            <h3 class="like-title">${s(i)}</h3>
            <div class="like-meta">${s(u)}</div>
          </a>
          <button class="ghost-button like-remove" type="button" data-uuid="${s(f)}" data-host="${s(a)}">Unlike</button>
          <p class="like-error" role="status"></p>
        </article>
      `}).join(""):'<div class="empty">No likes yet.</div>'}async function b(t){const e=t.closest(".like-card"),i=e==null?void 0:e.querySelector(".like-error"),n=t.dataset.uuid??"",a=t.dataset.host??"";if(!(!e||!n||!a)){t.disabled=!0,i&&(i.textContent="");try{await y(c,"undo_like",{uuid:n,host:a}),e.remove(),r.querySelector(".like-card")||(r.innerHTML=m([]))}catch(o){i&&(i.textContent=o instanceof Error?o.message:"Unlike failed"),t.disabled=!1}}}
