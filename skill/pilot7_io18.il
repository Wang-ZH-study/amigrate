;; pilot7_io18.il — 07B 切换：真实 OPA_D 副本 → n33/p33，写入 IO 尺寸（dbReplaceProp）
;; 尺寸来自 runs/2026-11-25-feasibility-io18（5mV 表）：L=0.5µm，W 为总宽，nf 为指数
(printf "\n=== PILOT7 START\n")
(load "/tmp/abConvertComponentParams.il")
(load "/tmp/abInvokeCdfCallbacks.il")

(unless (ddGetObj "port_pilot") (ddCreateLib "port_pilot" "/home/IC/port_pilot"))
(when (ddGetObj "port_pilot" "OPA_D") (ddDeleteObj (ddGetObj "port_pilot" "OPA_D")))

;; inst 类型 L(µm) W_total(µm) nf
(setq abPilotSizes
      (list
       (list "M1" "p" 0.5 7.63 1)
       (list "M2" "p" 0.5 7.63 1)
       (list "M3" "n" 0.5 1.84 1)
       (list "M4" "n" 0.5 1.84 1)
       (list "M5" "p" 0.5 15.77 1)
       (list "M6" "n" 0.5 20.42 2)
       (list "M7" "p" 0.5 87.43 5)
       (list "M8" "p" 0.5 15.77 1)))

(let (src dst changed cnt)
  (setq src (dbOpenCellViewByType "weekfour_last" "OPA_D" "schematic" "schematic" "r"))
  (setq dst (dbCopyCellView src "port_pilot" "OPA_D" "schematic"))
  (dbClose src)
  (dbClose dst)
  (setq dst (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "a"))
  (printf "copied: %d instances\n" (length dst~>instances))
  (setq changed (abConvertComponentParams "/tmp/conv.config" dst))
  (printf "convert changed=%L\n" changed)
  (setq cnt 0)
  (foreach i dst~>instances
    (when (equal i~>master~>libName "smic13mmrf_1233") (setq cnt (plus cnt 1))))
  (printf "converted instances=%d\n" cnt)
  ;; 写尺寸
  (foreach row abPilotSizes
    (let (name dev L W nf inst)
      (setq name (nth 0 row))
      (setq L (nth 2 row))
      (setq W (nth 3 row))
      (setq nf (nth 4 row))
      (setq inst nil)
      (foreach i dst~>instances
        (when (equal i~>name name) (setq inst i)))
      (when inst
        (dbReplaceProp inst "w" 'string (sprintf nil "%.3fu" W))
        (dbReplaceProp inst "l" 'string (sprintf nil "%.3fu" L))
        (dbReplaceProp inst "fingers" 'string (sprintf nil "%d" nf))
        (dbReplaceProp inst "m" 'string "1")
        (printf "write %s: master=%s/%s w=%L l=%L fingers=%L\n"
                name inst~>master~>libName inst~>master~>cellName
                (dbGet inst "w") (dbGet inst "l") (dbGet inst "fingers")))))
  (schCheck dst)
  (dbSave dst)
  (dbClose dst))

;; 重开验证
(let (cv)
  (setq cv (dbOpenCellViewByType "port_pilot" "OPA_D" "schematic" "schematic" "r"))
  (foreach i cv~>instances
    (when (member i~>name (list "M1" "M3" "M6" "M7"))
      (printf "reopen %s: %s/%s w=%L l=%L fingers=%L\n"
              i~>name i~>master~>libName i~>master~>cellName
              i~>w i~>l i~>fingers)))
  (dbClose cv))

(printf "=== PILOT7 DONE\n")
(exit)