import{s as D}from"./safe-url-Bow8sMhM.js";const C=new Intl.NumberFormat("en-US");function l(n){return n.replace(/[&<>"']/g,e=>{switch(e){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";case"'":return"&#39;";default:return e}})}function I(n){return n.instance_domain??n.instanceDomain??""}function V(n){const e=n.video_uuid??n.videoUuid??n.video_id??"";return e?String(e):""}function F(n){const e=I(n),t=V(n);return!e||!t?null:`${e}::${t}`}function P(n){return n.thumbnail_url??n.thumbnailUrl??n.preview_path??n.previewPath??null}function p(n){return n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"Unknown channel"}function H(n){const e=p(n).trim();if(!e)return"•";const a=e.replace(/[_\-]+/g," ").replace(/\s+/g," ").trim().split(" ").filter(Boolean);return a.length===1?a[0].slice(0,2).toUpperCase():`${a[0][0]}${a[1][0]}`.toUpperCase()}function B(n){return n.channel_avatar_url??n.channelAvatarUrl??n.account_avatar_url??n.accountAvatarUrl??n.avatar_url??n.avatarUrl??null}function $(n){if(n.channel_url)return n.channel_url;if(n.channelUrl)return n.channelUrl;const e=n.channel_name??n.channelName,t=n.instance_domain??n.instanceDomain;return e&&t?`https://${t}/video-channels/${encodeURIComponent(e)}`:"#"}function L(n){if(n.video_url)return n.video_url;if(n.videoUrl)return n.videoUrl;const e=n.video_uuid??n.videoUuid,t=n.instance_domain??n.instanceDomain;return e&&t?`https://${t}/videos/watch/${encodeURIComponent(e)}`:"#"}function R(n){const e=n.embed_path??n.embedPath??"";if(e.startsWith("http"))return e;const t=n.instance_domain??n.instanceDomain;if(e&&t)return`https://${t}${e}`;const a=n.video_uuid??n.videoUuid;return a&&t?`https://${t}/videos/embed/${encodeURIComponent(a)}`:""}function z(n){const e=n.published_at??n.publishedAt??null;if(!e||!Number.isFinite(e))return null;const t=Number(e);return t<1e12?t*1e3:t}function E(n){const e=Date.now(),t=Math.max(0,e-n),a=60*1e3,s=60*a,i=24*s,r=30*i,c=365*i;return t<a?"just now":t<s?`${Math.floor(t/a)} minutes ago`:t<i?`${Math.floor(t/s)} hours ago`:t<r?`${Math.floor(t/i)} days ago`:t<c?`${Math.floor(t/r)} months ago`:`${Math.floor(t/c)} years ago`}function T(n){if(!n||!Number.isFinite(n))return"0:00";const e=Math.max(0,Math.round(n)),t=Math.floor(e/3600),a=Math.floor(e%3600/60),s=e%60;return t>0?`${t}:${String(a).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${a}:${String(s).padStart(2,"0")}`}function d(n){return n==null||!Number.isFinite(n)?"--":C.format(n)}function G(n){if(n==null)return null;const e=Number(n);return Number.isFinite(e)?e:null}function K(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `}function Y(){return`
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `}function j(n,e){const t=new URLSearchParams,a=n.instance_domain??n.instanceDomain??"",s=n.video_id??n.video_uuid??n.videoUuid??"";s&&t.set("id",s),a&&t.set("host",a),n.title&&t.set("title",n.title);const i=n.channel_display_name??n.channelDisplayName??n.channel_name??n.channelName??"";i&&t.set("channel",i);const r=$(n);r&&r!=="#"&&t.set("channelUrl",r);const c=R(n);c&&t.set("embed",c);const o=L(n);return o&&o!=="#"&&t.set("url",o),`/video-page.html?${t.toString()}`}function J(n,e={}){const t=n.title??"Untitled video",a=P(n),s=T(n.duration??null),i=e.stats??null,r=(i==null?void 0:i.views)??null,c=(i==null?void 0:i.likes)??null,o=(i==null?void 0:i.dislikes)??null,b=p(n),_=$(n),h=B(n),g=H(n),f=z(n),m=f?E(f):null,U=m?` · ${m}`:"",k=h?`<img src="${l(h)}" alt="" loading="lazy" />`:`<span>${l(g)}</span>`,y=a?`<img src="${l(a)}" alt="${l(t)}" loading="lazy" />`:'<div class="thumb-fallback">No preview</div>',v=F(n),M=v?` data-video-key="${l(v)}"`:"",x=e.footerExtraHtml??"",u=e.reaction??null,N=u==="liked"?"stat likes active":"stat likes",S=u==="disliked"?"stat dislikes active":"stat dislikes",A=u==="liked"?'<span class="visually-hidden">You liked this</span>':u==="disliked"?'<span class="visually-hidden">You disliked this</span>':"";return`
    <article class="${u?`video-card ${u}`:"video-card"}"${M}>
      <a class="video-link" href="${l(j(n,e.apiParam))}">
        <div class="video-thumb">
          ${y}
          <span class="duration">${s}</span>
        </div>
        <div class="video-body">
          <h3 class="video-title">${l(t)}</h3>
          <div class="video-footer">
            <div class="channel-meta">
              <div class="channel-avatar" aria-hidden="true">${k}</div>
              <div class="channel-text">
                <a class="channel-link" href="${l(D(_))}" target="_blank" rel="noreferrer">
                  ${l(b)}
                </a>
                <div class="video-meta"><span data-stat="views">${d(r)}</span> views${l(U)}</div>
              </div>
            </div>
            <div class="video-stats">
              <span class="${N}">${K()}<span data-stat="likes">${d(c)}</span></span>
              <span class="${S}">${Y()}<span data-stat="dislikes">${d(o)}</span></span>
              ${A}
            </div>
            ${x}
          </div>
        </div>
      </a>
    </article>
  `}export{F as a,I as b,V as c,p as d,l as e,d as f,G as n,J as r,P as t,j as v};
