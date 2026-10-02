import{s as B}from"./safe-url-Bow8sMhM.js";const F=new Intl.NumberFormat("en-US");function l(n){return n.replace(/[&<>"']/g,a=>{switch(a){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";case"'":return"&#39;";default:return a}})}function L(n){return n.instance_domain??n.instanceDomain??""}function P(n){const a=n.video_uuid??n.videoUuid??n.video_id??"";return a?String(a):""}function H(n){const a=L(n),t=P(n);return!a||!t?null:`${a}::${t}`}function R(n){return n.thumbnail_url??n.thumbnailUrl??n.preview_path??n.previewPath??null}function b(n){return n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"Unknown channel"}function z(n){const a=b(n).trim();if(!a)return"•";const e=a.replace(/[_\-]+/g," ").replace(/\s+/g," ").trim().split(" ").filter(Boolean);return e.length===1?e[0].slice(0,2).toUpperCase():`${e[0][0]}${e[1][0]}`.toUpperCase()}function E(n){return n.channel_avatar_url??n.channelAvatarUrl??n.account_avatar_url??n.accountAvatarUrl??n.avatar_url??n.avatarUrl??null}function k(n){if(n.channel_url)return n.channel_url;if(n.channelUrl)return n.channelUrl;const a=n.channel_name??n.channelName,t=n.instance_domain??n.instanceDomain;return a&&t?`https://${t}/video-channels/${encodeURIComponent(a)}`:"#"}function T(n){if(n.video_url)return n.video_url;if(n.videoUrl)return n.videoUrl;const a=n.video_uuid??n.videoUuid,t=n.instance_domain??n.instanceDomain;return a&&t?`https://${t}/videos/watch/${encodeURIComponent(a)}`:"#"}function K(n){const a=n.embed_path??n.embedPath??"";if(a.startsWith("http"))return a;const t=n.instance_domain??n.instanceDomain;if(a&&t)return`https://${t}${a}`;const e=n.video_uuid??n.videoUuid;return e&&t?`https://${t}/videos/embed/${encodeURIComponent(e)}`:""}function Y(n){const a=n.published_at??n.publishedAt??null;if(!a||!Number.isFinite(a))return null;const t=Number(a);return t<1e12?t*1e3:t}function j(n){const a=Date.now(),t=Math.max(0,a-n),e=60*1e3,s=60*e,i=24*s,c=30*i,o=365*i;return t<e?"just now":t<s?`${Math.floor(t/e)} minutes ago`:t<i?`${Math.floor(t/s)} hours ago`:t<c?`${Math.floor(t/i)} days ago`:t<o?`${Math.floor(t/c)} months ago`:`${Math.floor(t/o)} years ago`}function q(n){if(!n||!Number.isFinite(n))return"0:00";const a=Math.max(0,Math.round(n)),t=Math.floor(a/3600),e=Math.floor(a%3600/60),s=a%60;return t>0?`${t}:${String(e).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${e}:${String(s).padStart(2,"0")}`}function h(n){return n==null||!Number.isFinite(n)?"--":F.format(n)}function J(n){if(n==null)return null;const a=Number(n);return Number.isFinite(a)?a:null}function p(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `}function $(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `}function W(n,a){const t=new URLSearchParams,e=n.instance_domain??n.instanceDomain??"",s=n.video_id??n.video_uuid??n.videoUuid??"";s&&t.set("id",s),e&&t.set("host",e),n.title&&t.set("title",n.title);const i=n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"";i&&t.set("channel",i);const c=k(n);c&&c!=="#"&&t.set("channelUrl",c);const o=K(n);o&&t.set("embed",o);const u=T(n);return u&&u!=="#"&&t.set("url",u),`/video-page.html?${t.toString()}`}function O(n,a={}){const t=n.title??"Untitled video",e=R(n),s=q(n.duration??null),i=a.stats??null,c=(i==null?void 0:i.views)??null,o=(i==null?void 0:i.likes)??null,u=(i==null?void 0:i.dislikes)??null,_=b(n),g=k(n),f=E(n),U=z(n),m=Y(n),v=m?j(m):null,y=v?` · ${v}`:"",M=f?`<img src="${l(f)}" alt="" loading="lazy" />`:`<span>${l(U)}</span>`,x=e?`<img src="${l(e)}" alt="${l(t)}" loading="lazy" />`:'<div class="thumb-fallback">No preview</div>',d=H(n),N=d?` data-video-key="${l(d)}"`:"",D=a.footerExtraHtml??"",r=a.reaction??null,S=r==="liked"?"stat likes active":"stat likes",A=r==="disliked"?"stat dislikes active":"stat dislikes",C=r==="liked"?'<span class="visually-hidden">You liked this</span>':r==="disliked"?'<span class="visually-hidden">You disliked this</span>':"",I=r?`video-card ${r}`:"video-card",V=a.actions&&d?`
      <div class="card-actions">
        <button type="button" class="card-action" data-card-action="like" aria-pressed="${r==="liked"}" title="Like">${p()}<span class="visually-hidden">Like</span></button>
        <button type="button" class="card-action" data-card-action="dislike" aria-pressed="${r==="disliked"}" title="Dislike">${$()}<span class="visually-hidden">Dislike</span></button>
        <button type="button" class="card-action" data-card-action="channel">Block channel</button>
        <button type="button" class="card-action" data-card-action="account">Block account</button>
        <span class="card-action-status" role="status"></span>
      </div>`:"";return`
    <article class="${I}"${N}>
      <a class="video-link" href="${l(W(n,a.apiParam))}">
        <div class="video-thumb">
          ${x}
          <span class="duration">${s}</span>
        </div>
        <div class="video-body">
          <h3 class="video-title">${l(t)}</h3>
          <div class="video-footer">
            <div class="channel-meta">
              <div class="channel-avatar" aria-hidden="true">${M}</div>
              <div class="channel-text">
                <a class="channel-link" href="${l(B(g))}" target="_blank" rel="noreferrer">
                  ${l(_)}
                </a>
                <div class="video-meta"><span data-stat="views">${h(c)}</span> views${l(y)}</div>
              </div>
            </div>
            <div class="video-stats">
              <span class="${S}">${p()}<span data-stat="likes">${h(o)}</span></span>
              <span class="${A}">${$()}<span data-stat="dislikes">${h(u)}</span></span>
              ${C}
            </div>
            ${D}
          </div>
        </div>
      </a>${V}
    </article>
  `}export{O as a,P as b,L as c,b as d,l as e,h as f,J as n,H as r,R as t,W as v};
