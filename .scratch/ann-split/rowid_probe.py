import sqlite3

c = sqlite3.connect(":memory:")
c.execute("create table video_embeddings(video_id text not null, instance_domain text not null, embedding blob not null, primary key(video_id,instance_domain))")
c.executemany("insert into video_embeddings(rowid,video_id,instance_domain,embedding) values (?,?,?,x'00')", [(7, 'a', 'h'), (3, 'b', 'h'), (42, 'c', 'g')])
c.create_function("ann_id_of", 2, lambda v, h: (hash((v, h)) & ((1 << 62) - 1)) | 1, deterministic=True)
c.execute("create table n(video_id text not null, instance_domain text not null, embedding blob not null, ann_id integer not null check(ann_id>0), primary key(video_id,instance_domain))")
c.execute("insert into n(rowid,video_id,instance_domain,embedding,ann_id) select rowid,video_id,instance_domain,embedding,ann_id_of(video_id,instance_domain) from video_embeddings")
before = c.execute("select rowid,video_id from video_embeddings order by 2").fetchall()
c.execute("drop table video_embeddings")
c.execute("alter table n rename to video_embeddings")
print(before, c.execute("select rowid,video_id from video_embeddings order by 2").fetchall())
